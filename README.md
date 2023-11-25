# llm-repl

An LLM plugin for an improved Chat experience! Forget about `!multi` and `!end` commands!

![](./.assets/demo.gif)

## Introduction

This plugin is an improvement over the `llm chat` command in the following areas:

- It introduces support for `rich` markdown to display colorful terminal colors.
- It introduces support for `prompt_toolkit` that allows to have a better experience between multi-line and single-line.

It mimics the `llm chat` options and arguments, so it's a direct substitute.

## Installation

### Using LLM

Install this plugin in the same environment as LLM:

```console
llm install llm-repl
```

### Nix

You can also install this plugin if you're using Nix / NixOS.

Add the following to your `flake.nix`:

```nix
{
    inputs = {
        nixpkgs.url = "github:nixos/nixpkgs/nixpkgs-unstable";
        llm-repl = {
            url = "github:aldoborrero/llm-repl";
            inputs.nixpkgs.follows = "nixpkgs";
        };
    };
}
```

And install it in your LLM instance:

```nix
{pkgs, inputs, ... } : {
    system.environmentPackages = with pkgs; [
        llm.withPlugins([
            inputs.llm-repl.packages.${system}.llm-repl
        ])
    ];
}
```

## License

See [LICENSE](./LICENSE) for more information.
