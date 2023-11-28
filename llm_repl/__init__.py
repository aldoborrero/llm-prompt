from typing import Any, Dict, List, Optional, Tuple
from typing import Any, Optional

import click
import llm
from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.formatted_text import AnyFormattedText, to_formatted_text
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
    @click.option("_template", "-t", "--template", help="Template to use")
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
        _template,
        param,
        options,
        no_stream,
        key,
    ):
        """
        Hold an ongoing conversation with a model on LLM.
        """
        # Retrieve db
        db = load_database(get_logs_db_path())

        # Retrieve conversation
        conversation = get_conversation(conversation_id, _continue)

        # Retrieve template
        template = get_template(_template, system)
        if template is not None and model_id is None and template.model:
            model_id = template.model

        # Pass any template_params
        template_params = dict(param)

        # Resolve the model
        model = get_model(model_id, conversation, key)
        if conversation is None:
            # Start a fresh conversation for this chat
            conversation = llm.Conversation(model=model)
        else:
            # Ensure it can see the API key
            conversation.model = model

        # Validate options
        model_options = validate_options(model, options)

        # Determine streaming capability
        should_stream = model.can_stream and not no_stream
        if not should_stream:
            model_options["stream"] = False

        run_repl_loop(db, model, model_options, conversation, template, template_params, system, should_stream)


def run_repl_loop(
    db: sqlite_utils.Database,
    model: llm.Model,
    model_options: dict[str, Any],
    conversation: llm.Conversation,
    template: Optional[llm.Template],
    template_params: dict[str, str],
    system: Optional[str],
    should_stream: bool = True,
) -> None:
    """
    Runs the REPL loop for interacting with a language model.
    """
    display_intro_message(model)
    while True:
        try:
            user_input = session.prompt(
                "> ",
                multiline=True,
                vi_mode=True,
                cursor=CursorShape.BLINKING_BLOCK,
                prompt_continuation=prompt_continuation,
            )
            if user_input is None:
                # If we receive None, it means the app is exiting
                break

            # Clean input
            user_input = user_input.strip()

            # Allow for empty lines in multi-line mode
            if not user_input and session.multi_line_mode:
                continue

            if template:
                try:
                    user_input, system = template.evaluate(user_input, template_params)
                except llm.Template.MissingVariables as ex:
                    raise click.ClickException(str(ex))

            # TODO: Handle better error responses and recover (if possible) from them
            response = conversation.prompt(user_input, system, **model_options)
            print_response(response=response, stream=should_stream)
            response.log_to_db(db)

            # system prompt only sent for the first message
            system = None

        except KeyboardInterrupt:
            continue  # User interrupted with Ctrl-C


def get_logs_db_path() -> str:
    logs_path = llm.cli.logs_db_path()
    logs_path.parent.mkdir(parents=True, exist_ok=True)
    return logs_path


def load_database(logs_path) -> sqlite_utils.Database:
    db = sqlite_utils.Database(logs_path)
    llm.migrations.migrate(db)
    return db


def get_model(model_id: Optional[str], conversation: Optional[llm.Conversation], key: Optional[str]) -> llm.Model:
    """
    Retrieves the specified model for use in a conversation.
    """
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


def get_conversation(conversation_id: Optional[str], _continue: int) -> llm.Conversation:
    """
    Retrieves an existing conversation or starts a new one based on the given parameters.
    """
    conversation = None
    if conversation_id or _continue:
        # Load the conversation - loads most recent if no ID provided
        try:
            conversation = llm.cli.load_conversation(conversation_id)
        except llm.UnknownModelError as ex:
            raise click.ClickException(str(ex))
    return conversation


def get_template(tpl: Optional[str], system: Optional[str]) -> Optional[llm.Template]:
    """
    Retrieves a template based on the provided template name, if specified.
    """
    template = None
    if template:
        if system:
            raise click.ClickException("Cannot use template and system prompt together")
        template = llm.cli.load_template(tpl)
    return template


def validate_options(model: llm.Model, options: list[tuple[str, str]]) -> dict[str, Any]:
    """
    Validates the given options against the model's expected configuration.
    """
    validated_options = {}
    if options:
        try:
            validated_options = dict((key, value) for key, value in model.Options(**dict(options)) if value is not None)
        except pydantic.ValidationError as ex:
            raise click.ClickException(llm.cli.render_errors(ex.errors()))
    return validated_options


def display_intro_message(model) -> None:
    console.clear()
    console.print(
        Panel(
            Markdown(
                f"""
# Welcome to LLM REPL!

## Chatting with {model.model_id}

- Press `Ctrl+Q` to end the conversation.
- Press `Ctrl+Space` to toggle between single-line and multi-line mode.
- Press `Alt+Enter` to submit your multi-line input, `Enter` to submit single-line input.
"""
            )
        )
    )


def bottom_toolbar() -> AnyFormattedText:
    """
    Creates and returns the bottom toolbar content for the prompt session.
    """
    app = get_app()

    input_mode = "Multi-line mode" if session.multi_line_mode else "Single-line mode"

    vi_mode = app.vi_state.input_mode
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

    terminal_width = app.output.get_size().columns
    mode_display_length = sum(len(text) for _, text in mode_display)
    right_text_length = sum(len(text) for _, text in right_part_commands)

    # Calculate space length considering the entire length of mode_display
    space_length = terminal_width - right_text_length - mode_display_length
    space_length = max(space_length, 0)  # Ensure it's not negative

    space = ("class:toolbar", " " * space_length)

    return to_formatted_text(mode_display + [space] + right_part_commands)


def setup_prompt_session() -> PromptSession:
    """
    Sets up and returns a new prompt session for user input.
    """
    history = InMemoryHistory()
    key_bindings = create_key_bindings()

    session = MultiLinePromptSession(
        history=history, key_bindings=key_bindings, bottom_toolbar=bottom_toolbar, style=style, multiline=True
    )

    return session


def create_key_bindings() -> KeyBindings:
    """
    Create custom key bindings for the prompt session.
    """
    kb = KeyBindings()

    @kb.add("escape", "enter")
    def handle_alt_enter(event):
        """
        Handle Alt+Enter to submit text in multi-line mode.
        """
        if session.multi_line_mode:
            event.current_buffer.validate_and_handle()

    @kb.add("enter")
    def handle_enter(event):
        """
        Handle Enter key to submit text directly in single-line mode. Otherwise a new line is inserted in multi-line mode.
        """
        if session.multi_line_mode:
            # In multi-line mode, insert a new line without submitting
            event.current_buffer.insert_text("\n")
        else:
            # In single-line mode, submit the text
            event.current_buffer.validate_and_handle()

    @kb.add("c-space")
    def toggle_multi_line_mode(event):
        """
        Toggle between single-line and multi-line mode without echoing to the terminal.
        """
        session.toggle_multi_line_mode()
        event.app.current_buffer.reset()

    @kb.add("c-q")
    def exit(event):
        """
        Handle Ctrl+Q to close the application.
        """
        event.app.exit()

    return kb


def prompt_continuation(width: int, line_number: int, is_soft_wrap: bool) -> str:
    """
    Generates the continuation prompt string for the multi-line input messages.
    """
    return "." * width


def create_response_panel(content: str) -> Panel:
    """
    Creates and returns a panel for displaying a response in a rich text format.
    """
    return Padding(Panel(content, title="LLM", title_align="left"), (1, 1))


def print_response(response: llm.Response, stream: bool = True) -> None:
    """
    Prints the response from the language model to the console.
    """
    if stream:
        md = ""
        with Live(Markdown(md), console=console, auto_refresh=20) as live:
            for chunk in response:
                md += chunk
                live.update(create_response_panel(Markdown(md)))
    else:
        console.print(create_response_panel(Markdown(response.text())))


class MultiLinePromptSession(PromptSession):
    def __init__(self, *args, **kwargs):
        self.multi_line_mode = False
        super().__init__(*args, **kwargs)

    def toggle_multi_line_mode(self):
        self.multi_line_mode = not self.multi_line_mode


# TODO: Remove this global variable
session = setup_prompt_session()
