{
  description = "llm-repl / An improved chat experience for LLM";

  nixConfig = {
    extra-substituters = [
      "https://nix-community.cachix.org"
    ];
    extra-trusted-public-keys = [
      "nix-community.cachix.org-1:mB9FSh9qf2dCimDSUo8Zy7bkq5CX+/rkCWyvRCYg3Fs="
    ];
  };

  inputs = {
    # packages
    nixpkgs.url = "github:nixos/nixpkgs/nixpkgs-unstable";

    # flake-parts
    flake-parts = {
      url = "github:hercules-ci/flake-parts";
      inputs.nixpkgs-lib.follows = "nixpkgs";
    };
    flake-root.url = "github:srid/flake-root";

    # utilities
    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    devshell = {
      url = "github:numtide/devshell";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    lib-extras = {
      url = "github:aldoborrero/lib-extras";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    devour-flake = {
      url = "github:srid/devour-flake";
      flake = false;
    };
  };

  outputs = inputs @ {
    flake-parts,
    nixpkgs,
    ...
  }: let
    lib = nixpkgs.lib.extend (l: _: (inputs.lib-extras.lib l));
  in
    flake-parts.lib.mkFlake
    {
      inherit inputs;
      specialArgs = {inherit lib;};
    }
    {
      imports = [
        inputs.devshell.flakeModule
        inputs.flake-parts.flakeModules.easyOverlay
        inputs.flake-root.flakeModule
        inputs.treefmt-nix.flakeModule
      ];

      debug = false;

      systems = ["x86_64-linux"];

      perSystem = {
        pkgs,
        lib,
        config,
        system,
        self',
        ...
      }: {
        # nixpkgs
        _module.args = {
          pkgs = lib.nix.mkNixpkgs {
            inherit system;
            inherit (inputs) nixpkgs;
            overlays = [
              (final: _: {
                devour-flake = final.callPackage inputs.devour-flake {};
              })
            ];
          };
        };

        # packages
        packages = {
          llm-repl = pkgs.python311Packages.buildPythonPackage {
            name = "llm-repl";
            version = "0.1.0-dev";
            pyproject = true;

            src = lib.cleanSource ./.;

            buildInputs = with pkgs.python311Packages; [
              llm
            ];

            propagatedBuildInputs = with pkgs.python311Packages; [
              click
              prompt_toolkit
              pydantic
              pygments
              rich
              sqlite-utils
              textual
            ];
          };

          mdformat-custom = with pkgs.python311Packages;
            mdformat.withPlugins [
              mdformat-footnote
              mdformat-gfm
              mdformat-simple-breaks
            ];
        };

        # devshells
        devshells.default = {
          name = "llm-repl";
          packages = with pkgs; [
            (llm.withPlugins [self'.packages.llm-repl])
            python311
            poetry
            vhs
          ];
          env = [
            {
              name = "LLM_USER_PATH";
              eval = "$PRJ_DATA_DIR/io.datasette.llm";
            }
          ];
          commands = [
            {
              name = "fmt";
              category = "nix";
              help = "format the source tree";
              command = ''nix fmt'';
            }
            {
              name = "check";
              category = "nix";
              help = "check the source tree";
              command = ''nix flake check'';
            }
          ];
        };

        # treefmt
        treefmt.config = {
          inherit (config.flake-root) projectRootFile;
          flakeFormatter = true;
          flakeCheck = true;
          programs = {
            alejandra.enable = true;
            black.enable = true;
            deadnix.enable = true;
            deno.enable = true;
            mdformat.enable = true;
            ruff.enable = true;
            shfmt.enable = true;
          };
          settings.formatter = {
            deno.excludes = ["*.md"];
            mdformat.command = lib.mkDefault self'.packages.mdformat-custom;
          };
        };

        # checks
        checks = {
          nix-build-all = pkgs.writeShellApplication {
            name = "nix-build-all";
            runtimeInputs = [
              pkgs.nix
              pkgs.devour-flake
            ];
            text = ''
              # Make sure that flake.lock is sync
              nix flake lock --no-update-lock-file

              # Do a full nix build (all outputs)
              devour-flake . "$@"
            '';
          };
        };
      };
    };
}
