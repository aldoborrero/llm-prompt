# llm-prompt

[![PyPI](https://img.shields.io/pypi/v/llm-prompt.svg)](https://pypi.org/project/llm-prompt/)
[![Changelog](https://img.shields.io/github/v/release/aldoborrero/llm-prompt?include_prereleases&label=changelog)](https://github.com/aldoborrero/llm-prompt/releases)
[![Tests](https://github.com/aldoborrero/llm-prompt/workflows/Test/badge.svg)](https://github.com/aldoborrero/llm-prompt/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/aldoborrero/llm-prompt/blob/main/LICENSE)

An [LLM](https://github.com/simonw/llm) plugin for an improved chat experience! Forget about `!multi` and `!end` commands!

![](./.assets/demo.gif)

## Introduction

Just invoke it with:

```console
llm prompt
```

This plugin is an improvement over the `llm chat` command in the following areas:

- It introduces support for [rich](https://github.com/Textualize/rich) to display colorful terminal outputs.
- It introduces support for [prompt_toolkit](https://python-prompt-toolkit.readthedocs.io/en/master/) that allows to have a better experience between multi-line and single-line (yes, you'll have access to `vim` keystyle bindings).

It mimics the `llm chat` options and arguments, so it's a direct substitute.

## Installation

### Using LLM

Install this plugin in the same environment as LLM:

```console
llm install llm-prompt
```

### Nix

You can also install this plugin if you're using Nix / NixOS.

Add the following to your `flake.nix`:

```nix
{
    inputs = {
        nixpkgs.url = "github:nixos/nixpkgs/nixpkgs-unstable";
        llm-prompt = {
            url = "github:aldoborrero/llm-prompt";
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
            inputs.llm-prompt.packages.${system}.llm-prompt
        ])
    ];
}
```

## License

See [LICENSE](./LICENSE) for more information.
