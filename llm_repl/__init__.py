import click
import llm
from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.formatted_text import to_formatted_text
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.vi_state import InputMode
from prompt_toolkit.styles import Style
import pydantic
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
import sqlite_utils

console = Console()

style = Style.from_dict(
    {
        "toolbar": "bg:#333333 #aaaaaa",
        "key": "bold",
    }
)


@llm.hookimpl
def register_commands(cli):
    @cli.command(name="repl")
    @click.option("-s", "--system", help="System prompt to use")
    @click.option("model_id", "-m", "--model", help="Model to use")
    @click.option(
        "_continue",
        "-c",
        "--continue",
        is_flag=True,
        flag_value=-1,
        help="Continue the most recent conversation.",
    )
    @click.option(
        "conversation_id",
        "--cid",
        "--conversation",
        help="Continue the conversation with the given ID.",
    )
    @click.option("-t", "--template", help="Template to use")
    @click.option(
        "-p",
        "--param",
        multiple=True,
        type=(str, str),
        help="Parameters for template",
    )
    @click.option(
        "options",
        "-o",
        "--option",
        type=(str, str),
        multiple=True,
        help="key/value options for the model",
    )
    @click.option("--no-stream", is_flag=True, help="Do not stream output")
    @click.option("--key", help="API key to use")
    def repl(
        system,
        model_id,
        _continue,
        conversation_id,
        template,
        param,
        options,
        no_stream,
        key,
    ):
        """
        Hold an ongoing conversation with a model on LLM.
        """
        # Retrieve db
        db = load_database(get_log_db_path())

        # Retrieve conversation
        conversation = get_conversation(conversation_id, _continue)

        template_obj, params = get_template_obj(template, system, param)
        if template_obj is not None and model_id is None and template_obj.model:
            model_id = template_obj.model

        # Resolve the model
        model = get_model(model_id, conversation, key)
        if conversation is None:
            # Start a fresh conversation for this chat
            conversation = llm.Conversation(model=model)
        else:
            # Ensure it can see the API key
            conversation.model = model

        # Validate options
        validated_options = validate_options(model, options)

        # Determine streaming capability
        should_stream = model.can_stream and not no_stream
        if not should_stream:
            validated_options["stream"] = False

        run_repl_loop(template_obj, params, conversation, system, db, validated_options, model)


def run_repl_loop(template_obj, params, conversation, system, db, validated_options, model):
    console.clear()
    console.print(
        Panel(
            Markdown(
                f"""
# Chatting with {model.model_id}

- Press `Ctrl+Q` to end the conversation.
- Press `Ctrl+Space` to toggle between single-line and multi-line mode.
- Press `Alt+Enter` to submit your multi-line input, `Enter` to submit single-line input (it supports vi key-bindings).

"""
            )
        )
    )

    history = InMemoryHistory()
    bindings = KeyBindings()

    multi_line_mode = False  # Start in single-line mode

    @bindings.add("escape", "enter")
    def handle_alt_enter(event):
        "Handle Alt+Enter to submit text in multi-line mode."
        if multi_line_mode:
            event.current_buffer.validate_and_handle()

    @bindings.add("enter")
    def handle_enter(event):
        "Handle Enter key differently based on the current mode."
        if multi_line_mode:
            # In multi-line mode, insert a new line without submitting
            event.current_buffer.insert_text("\n")
        else:
            # In single-line mode, submit the text
            event.current_buffer.validate_and_handle()

    @bindings.add("c-space")
    def toggle_multi_line_mode(event):
        "Toggle between single-line and multi-line mode without echoing to the terminal."
        nonlocal multi_line_mode
        multi_line_mode = not multi_line_mode

        # Clean the current buffer
        event.app.current_buffer.reset()

    @bindings.add("c-q")
    def exit(event):
        "Bind Ctrl+Q to close the application"
        event.app.exit()

    def prompt_continuation(width, line_number, is_soft_wrap):
        return "." * width

    def bottom_toolbar():
        "Displays a toolbar that shows the current input mode and align commands to the right."
        input_mode = "Multi-line mode" if multi_line_mode else "Single-line mode"

        vi_mode = get_app().vi_state.input_mode
        vi_mode_display = "NORMAL" if vi_mode == InputMode.NAVIGATION else "INSERT"

        mode_display = [
            ("class:toolbar", f"LLM ({input_mode}) "),
            ("class:toolbar", f"{vi_mode_display}"),
        ]

        right_part_commands = [
            ("class:separator", "|"),
            ("class:key", "Ctrl+Space"),
            ("class:separator", "|"),
            ("class:toolbar", " Toggle Mode "),
            ("class:separator", "|"),
            ("class:key", "Ctrl+Q"),
            ("class:separator", "|"),
            ("class:toolbar", " Quit "),
        ]

        terminal_width = get_app().output.get_size().columns

        # Calculate the combined length of the displayable text for the right part
        right_text_length = sum(len(text) for class_name, text in right_part_commands)

        # Calculate leftover space based on terminal size minus the right-side text length
        space_length = terminal_width - right_text_length - len(mode_display[0][1])

        # If space_length is negative, which means the terminal is too narrow, set it to zero
        space_length = max(space_length, 0)

        space = ("class:toolbar", " " * space_length)

        return to_formatted_text(mode_display + [space] + right_part_commands)

    session = PromptSession(
        history=history,
        key_bindings=bindings,
        bottom_toolbar=bottom_toolbar,
        style=style,
        multiline=True,  # Enable multiline mode in PromptSession.
    )

    while True:
        try:
            user_input = session.prompt(
                "> ",
                multiline=multi_line_mode,
                vi_mode=True,
                cursor=CursorShape.BLINKING_BLOCK,
                prompt_continuation=prompt_continuation,
            )
            if user_input is None:
                # If we receive None, it means the app is exiting
                break

            user_input = user_input.strip()

            # Allow for empty lines in multi-line mode
            if not user_input and multi_line_mode:
                continue

            if template_obj:
                try:
                    user_input, system = template_obj.evaluate(user_input, params)
                except llm.Template.MissingVariables as ex:
                    raise click.ClickException(str(ex))

            # system prompt only sent for the first message
            system = None

            response = conversation.prompt(user_input, system, **validated_options)
            print_response(response=response, stream=True)
            response.log_to_db(db)
        except KeyboardInterrupt:
            continue  # User interrupted with Ctrl-C


def get_log_db_path():
    log_path = llm.cli.logs_db_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return log_path


def load_database(log_path):
    db = sqlite_utils.Database(log_path)
    llm.migrations.migrate(db)
    return db


def get_model(model_id, conversation, key):
    # Figure out which model we are using
    if model_id is None:
        if conversation:
            model_id = conversation.model.model_id
        else:
            model_id = llm.cli.get_default_model()

    # Now resolve the model
    try:
        model = llm.get_model(model_id)
    except KeyError:
        raise click.ClickException("'{}' is not a known model".format(model_id))

    # Provide the API key, if one is needed and has been provided
    if model.needs_key:
        model.key = llm.get_key(key, model.needs_key, model.key_env_var)

    return model


def get_conversation(conversation_id, _continue):
    conversation = None
    if conversation_id or _continue:
        # Load the conversation - loads most recent if no ID provided
        try:
            conversation = llm.cli.load_conversation(conversation_id)
        except llm.UnknownModelError as ex:
            raise click.ClickException(str(ex))
    return conversation


def get_template_obj(template, system, param):
    template_obj = None
    params = dict(param)
    if template:
        if system:
            raise click.ClickException("Cannot use template and system prompt together")
        template_obj = llm.cli.load_template(template)
    return template_obj, params


def validate_options(model, options):
    validated_options = {}
    if options:
        try:
            validated_options = dict((key, value) for key, value in model.Options(**dict(options)) if value is not None)
        except pydantic.ValidationError as ex:
            raise click.ClickException(llm.cli.render_errors(ex.errors()))
    return validated_options


def create_response_panel(content):
    return Padding(Panel(content, title="LLM", title_align="left"), (1, 1))


def print_response(response: llm.Response, stream: bool = True):
    if stream:
        md = ""
        with Live(Markdown(""), console=console, auto_refresh=20) as live:
            for chunk in response:
                md += chunk
                live.update(create_response_panel(Markdown(md)))
    else:
        console.print(create_response_panel(Markdown(response.text())))
