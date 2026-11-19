{
  description = "Turn a text file of songs into tagged MP3s: Spotify metadata and cover art, best-match YouTube audio via yt-dlp";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      inherit (nixpkgs) lib;
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];
      forAllSystems = f: lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      pyproject = builtins.fromTOML (builtins.readFile ./pyproject.toml);
    in
    {
      packages = forAllSystems (pkgs: {
        trackfetch = pkgs.python3Packages.buildPythonApplication {
          pname = "trackfetch";
          inherit (pyproject.project) version;
          pyproject = true;

          src = lib.cleanSource ./.;

          build-system = [ pkgs.python3Packages.setuptools ];

          dependencies = with pkgs.python3Packages; [
            mutagen
            pillow
            requests
            spotipy
            yt-dlp
          ];

          # trackfetch calls these as external programs.
          makeWrapperArgs = [
            "--prefix PATH : ${
              lib.makeBinPath [
                pkgs.yt-dlp
                pkgs.ffmpeg
                pkgs.deno
              ]
            }"
          ];

          nativeCheckInputs = [ pkgs.python3Packages.pytestCheckHook ];

          pythonImportsCheck = [ "trackfetch" ];

          meta = {
            description = "Turn a text file of songs into tagged MP3s using Spotify metadata and YouTube audio";
            homepage = "https://github.com/ByteMe6/trackfetch";
            changelog = "https://github.com/ByteMe6/trackfetch/blob/master/CHANGELOG.md";
            license = lib.licenses.gpl3Plus;
            mainProgram = "trackfetch";
            platforms = lib.platforms.unix;
          };
        };

        default = self.packages.${pkgs.stdenv.hostPlatform.system}.trackfetch;
      });

      apps = forAllSystems (pkgs: {
        default = {
          type = "app";
          program = lib.getExe self.packages.${pkgs.stdenv.hostPlatform.system}.trackfetch;
          meta.description = "Run trackfetch";
        };
      });

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (
              ps: with ps; [
                mutagen
                pillow
                requests
                spotipy
                yt-dlp
                pytest
                pytest-cov
              ]
            ))
            pkgs.ruff
            pkgs.yt-dlp
            pkgs.ffmpeg
            pkgs.deno
          ];
        };
      });

      formatter = forAllSystems (pkgs: pkgs.nixfmt-tree);
    };
}
