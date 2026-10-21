{
  description = "ROBOT -> obo2tex pipeline dev shell";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.flake-utils.url = "github:numtide/flake-utils";

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let pkgs = nixpkgs.legacyPackages.${system};
      in {
        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.uv
            pkgs.python3   # interpreter uv will use (managed downloads don't run on NixOS)
            pkgs.jdk       # needed by ROBOT
            pkgs.curl      # the ./robot wrapper downloads robot.jar
          ];
          env = {
            UV_PYTHON_DOWNLOADS = "never";   # always use the Nix python
            UV_PYTHON = "${pkgs.python3}/bin/python3";
          };
        };
      });
}
