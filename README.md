# ASTwalker
Lightweight AST walker for Python using pyvis and NetworkX

### Legend

🟨 File  
🟦 Module  
⬜ Function  
🔴 Static-flow

<img src="/img/astwalker.png" alt="AST Walker Diagram" width="800">

## Arguments & Flags

`astwalker` accepts the following options. Run:

```bash
astwalker --help
```

to display:

```text
Usage:
  astwalker [--root <root_dir>] [--output <output_path>] [--debug]

Options:

  --root <root_dir>
      Root package directory to scan (defaults to current working directory).

  --output <output_path>
      HTML output file or directory (defaults to same as `--root`).

  --debug
      Enable debug-level logging.
```

### Notes

- Omitting `--root` makes ASTwalker scan your current directory.  
- Omitting `--output` writes the generated `pyvis_graph.html` into the root directory.  
- `--debug` prints verbose parsing and pruning logs to the console.  



