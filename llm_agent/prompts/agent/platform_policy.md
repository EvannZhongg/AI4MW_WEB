## Platform Policy

Current server platform: {{ system }}

- Prefer built-in `grep`, `glob`, `list_dir`, and `read_file` over shell-style assumptions.
- The backend may run on Windows or Linux depending on deployment; avoid assuming GNU command-line tools are available.
- Use UTF-8 text assumptions for readable source and docs. If a file is binary, protected, or too large, explain that limitation instead of guessing.
