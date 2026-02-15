# Ansible Callback Suite

[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Language](https://img.shields.io/badge/language-python-blue.svg)](https://www.python.org/)
[![Ansible](https://img.shields.io/badge/ansible-callback_suite-red.svg)](https://docs.ansible.com/)

This repository is an Ansible callback suite.

It currently documents one callback plugin (`changed_debug`) and is structured to host additional callback plugins over time.

## Available callbacks

### `changed_debug` (stdout)

`changed_debug` outputs a compact JSON document with:
- task/debug events
- changed task events
- failed/unreachable events
- a final play recap per host

By default, unchanged `ok` tasks are hidden to reduce noise.

## Enable `changed_debug`

From the project directory, export:

```bash
export ANSIBLE_STDOUT_CALLBACK=changed_debug
export ANSIBLE_CALLBACK_PLUGINS="$(pwd)/callback_plugins"
```

Alternative with `ansible.cfg`:

```ini
[defaults]
stdout_callback = changed_debug
callback_plugins = ./callback_plugins
```

Optional: show unchanged `ok` task events:

```bash
export ANSIBLE_CHANGED_DEBUG_SHOW_OK=true
```

You can also use:

```bash
export CHANGED_DEBUG_SHOW_OK=true
```

## Run with `changed_debug`

```bash
ansible-playbook -i inventory site.yml
```

The output is emitted as one JSON object containing `events` and `play_recap`.
