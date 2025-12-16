# Config Caddy

![Travis CI](https://travis-ci.org/tstapler/cfgcaddy.svg?branch=master)
[![PyPI version](https://badge.fury.io/py/cfgcaddy.svg)](https://badge.fury.io/py/cfgcaddy)


Config Caddy is a tool used for managing your configuration files. 

One way to version your configuration files is to keep them in a [git](https://git-scm.com/) repository. This has several drawbacks, among them, git requires the files it manages to be located within a single file tree. You can overcome this limitation by using symbolic links. The links point from locations in your filesystem such as `/etc/someconfig.conf`to files within the git repository like `$HOME/tstapler/dotfiles/someconfig.conf`.

Config Caddy creates symlinks to your dotfiles directory, so you don't have to. Each time you add a new file to your dotfiles repo, run `cfgcaddy link` to generate symlinks. By default `cfgcaddy` will create links from files in the dotfiles repo to their relative location in your home directory. `cfgcaddy` will also read from a configuration file. This allows the user to ignore certain files and create more complex linking relationships.


## Usage

2. Install using pip

```shell

pip install cfgcaddy

````
2. Generate or import a configuration file for cfgcaddy

```shell
cfgcaddy init --help

Usage: cfgcaddy init [OPTIONS] SRC_DIRECTORY DEST_DIRECTORY

  Create or import a caddy config

Options:
  -c, --config PATH  The path to your cfgcaddy.yml
  --help             Show this message and exit.

cfgcaddy init $HOME/dotfiles $HOME
```

3. Run the linker
```bash
cfgcaddy link
```

## Configuration File Format

`cfgcaddy` uses a configuration file to store important information about your configuration. The `.cfgcaddy.yml` consists of several parts. A *preferences* section which contains information like where your dotfiles are located and where you want them linked to, A *links* section where you can specify more complex symlinks, and an `ignore` section where you specify files you do not want managed by `cfgcaddy`.

Config files for cfgcaddy are stored in your home directory by default. `$HOME/.cfgcaddy.yml`

A sample `.cfgcaddy.yml` which leverages most features can be found [here](https://github.com/tstapler/dotfiles/blob/master/.cfgcaddy.yml)

### Preferences

The `preferences` section supports the following options:

- `linker_src`: Path to your dotfiles directory
- `linker_dest`: Path where configs should be linked to
- `link_mode`: (Optional) Link mode to use:
  - `auto` (default): Auto-detect based on platform and destination
  - `symlink`: Always use symbolic links
  - `copy`: Always copy files instead of symlinking

Example:
```yaml
preferences:
  linker_src: ~/dotfiles
  linker_dest: ~
  link_mode: auto  # Optional, defaults to auto
```

## Termux Support (Android)

`cfgcaddy` has full support for running on Android via [Termux](https://termux.com/).

### Setup on Termux

1. Install Python and pip in Termux:
```bash
pkg install python
```

2. Install cfgcaddy:
```bash
pip install cfgcaddy
```

3. (Optional) Set up shared storage access:
```bash
termux-setup-storage
```

4. Initialize cfgcaddy:
```bash
cfgcaddy init ~/dotfiles ~
```

### Shared Storage Considerations

Android's shared storage (typically `/storage/emulated/0` or `~/storage/shared` in Termux) uses FAT or exFAT filesystems that **do not support symbolic links**. When cfgcaddy detects you're running on Termux with destinations on shared storage, it will automatically fall back to copying files instead of creating symlinks.

#### Link Modes

- **auto** (recommended): Automatically detects whether the destination supports symlinks and uses the appropriate method
- **symlink**: Always tries to create symlinks (will fail on shared storage)
- **copy**: Always copies files instead of symlinking (slower, but works everywhere)

#### Example Termux Configuration

For linking configs within Termux's private storage (symlinks work):
```yaml
preferences:
  linker_src: ~/dotfiles
  linker_dest: ~
  link_mode: auto  # Will use symlinks
```

For linking to shared storage (will use copies):
```yaml
preferences:
  linker_src: ~/dotfiles
  linker_dest: ~/storage/shared/configs
  link_mode: auto  # Will use copies
```

### Termux Best Practices

1. Keep your dotfiles in Termux's home directory (`~`) or on shared storage
2. Use `link_mode: auto` to let cfgcaddy choose the best method
3. Be aware that copy mode means you'll need to re-run `cfgcaddy link` after editing files in your dotfiles directory
4. Consider using git hooks to automatically run `cfgcaddy link` after pulling changes

## Development

1. Clone the repository

```shell
git clone https://github.com/tstapler/cfgcaddy
cd cfgcaddy
```

2. Install [uv](https://github.com/astral-sh/uv) if you haven't already

```shell
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or with pip
pip install uv
```

3. Sync dependencies and create virtual environment

```shell
uv sync --all-extras
```

4. Run tests

```shell
uv run pytest tests/
```

5. Format and lint code

```shell
# Format code
uv run ruff format .

# Check linting
uv run ruff check .

# Fix linting issues automatically
uv run ruff check --fix .
```

6. Run cfgcaddy in development

```shell
uv run cfgcaddy --help
```

### Development Tools

This project uses:
- **uv** - Fast Python package installer and resolver
- **ruff** - Fast Python linter and formatter (replaces Black, isort, flake8)
- **pytest** - Testing framework
- **mypy** - Type checking
- **hatchling** - Build backend

## Motivation/Prior Art

I'm an automation fiend, this tool grew out of a personal need to manage my configurations across multiple machines and operating systems. It fits my needs and I'll add features as I need them (Like Windows support). PRs are always welcome :)

Here are several projects that I've drawn inspiration from:

- https://github.com/charlesthomas/linker
- https://github.com/thoughtbot/rcm
