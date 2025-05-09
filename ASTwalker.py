import argparse
import ast
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import networkx as nx
from pyvis.network import Network
from tqdm import tqdm

# ─── CONFIG ───
ROOT_PKG = ''
IGNORE_MODULES = {
    'logging', 'os', 'sys', 'timeit', 'pytz', 'datetime', 'numpy', 'traceback'
}
STYLE = {
    'file': {
        'shape': 'box',
        'color': {
            'background': '#F1C40F',
            'border':     '#B7950B',
        },
        'borderWidth': 1,
        'font': {'color': '#000000'},
    },
    'module': {
        'shape': 'box',
        'color': {
            'background': '#4A90E2',
            'border':     '#1F78B4',
        },
        'borderWidth': 2,
        'font': {'color': '#000000'},
    },
    'function': {
        'shape': 'ellipse',
        'color': {
            'background': '#F5F5F5',
            'border':     '#CCCCCC',
        },
        'borderWidth': 1,
        'font': {'color': '#000000'},
    },
    'import_edge': {'color': '#888888'},
    'call_edge':   {'color': '#666666'},
}
# ──────────────


def scan_py_files(root_dir: Path) -> List[Path]:
    return list(root_dir.rglob('*.py'))


def module_name(path: Path, root_dir: Path) -> str:
    rel = path.relative_to(root_dir).with_suffix('')
    return ROOT_PKG + '.' + '.'.join(rel.parts)


class CodeAnalyzer(ast.NodeVisitor):
    def __init__(self, modname: str):
        self.mod = modname
        self.imports: Set[str] = set()
        self.aliases: Dict[str, str] = {}
        self.func_defs: Dict[str, str] = {}
        self.calls: List[Tuple[str, str]] = []
        self.current_fn: Optional[str] = None
        self.current_class: Optional[str] = None

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            full = alias.name
            asn = alias.asname or alias.name
            self.aliases[asn] = full
            if full.startswith(ROOT_PKG):
                self.imports.add(full)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ''
        if node.level:
            parent = self.mod.rsplit('.', node.level)[0]
            module = f"{parent}.{module}" if module else parent
        for alias in node.names:
            if alias.name == '*':
                continue
            name = alias.name
            asn = alias.asname or name
            full = f"{module}.{name}" if module else name
            self.aliases[asn] = full
            if full.startswith(ROOT_PKG):
                self.imports.add(module)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        prev = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = prev

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        qual = f"function:{self.mod}.{node.name}"
        if self.current_class:
            qual = f"function:{self.mod}.{self.current_class}.{node.name}"
        self.func_defs[node.name] = qual
        prev = self.current_fn
        self.current_fn = qual
        self.generic_visit(node)
        self.current_fn = prev

    def visit_Call(self, node: ast.Call) -> None:
        callee = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name in self.func_defs:
                callee = self.func_defs[name]
            elif name in self.aliases:
                full = self.aliases[name]
                if full.startswith(ROOT_PKG):
                    if '.' in full:
                        callee = f"function:{full}"
                    else:
                        callee = f"module:{full}"
        elif isinstance(node.func, ast.Attribute):
            val = node.func.value
            attr = node.func.attr
            if isinstance(val, ast.Name) and val.id in self.aliases:
                full = self.aliases[val.id]
                if full.startswith(ROOT_PKG):
                    callee = f"function:{full}.{attr}"
        if callee:
            caller = self.current_fn or f"module:{self.mod}"
            self.calls.append((caller, callee))
        self.generic_visit(node)


def build_graph(root_dir: Path) -> nx.DiGraph:
    G = nx.DiGraph()
    files = scan_py_files(root_dir)
    results: List[Tuple[Path, str, CodeAnalyzer]] = []
    for f in tqdm(files, desc='Parsing files'):
        mod = module_name(f, root_dir)
        tree = ast.parse(f.read_text(encoding='utf-8'), filename=str(f))
        ca = CodeAnalyzer(mod)
        ca.visit(tree)
        results.append((f, mod, ca))

    for fpath, mod, ca in results:
        file_id = f"file:{mod}"
        G.add_node(file_id, label=fpath.name, **STYLE['file'])

        mod_id = f"module:{mod}"
        G.add_node(mod_id, label=mod, **STYLE['module'])
        G.add_edge(file_id, mod_id, **STYLE['import_edge'])

        for im in ca.imports:
            tgt = f"module:{im}"
            G.add_node(tgt, label=im, **STYLE['module'])
            G.add_edge(mod_id, tgt, **STYLE['import_edge'])

        for qual in ca.func_defs.values():
            fn_lbl = qual.split(':', 1)[1].split('.')[-1]
            G.add_node(qual, label=fn_lbl, **STYLE['function'])
            G.add_edge(
                mod_id, qual,
                color=STYLE['import_edge']['color'],
                dashes=True
            )

        for caller, callee in ca.calls:
            for node_id in (caller, callee):
                if not G.has_node(node_id):
                    kind, name = node_id.split(':', 1)
                    if kind == 'function':
                        G.add_node(node_id,
                                   label=name.split('.')[-1],
                                   **STYLE['function'])
                    elif kind == 'module':
                        G.add_node(node_id,
                                   label=name,
                                   **STYLE['module'])
                    else:
                        G.add_node(node_id, label=name)
            G.add_edge(caller, callee, **STYLE['call_edge'])

    return G


def prune_graph(G: nx.DiGraph) -> None:
    to_rm = [
        n for n in G.nodes()
        if n.split(':', 1)[1] in IGNORE_MODULES
        or any(n.split(':', 1)[1].startswith(ign + '.') for ign in IGNORE_MODULES)
    ]
    G.remove_nodes_from(to_rm)


def render_graph(G: nx.DiGraph, output: Path) -> None:
    net = Network(
        height='100vh',
        width='100vw',
        bgcolor='#1e1e1e', font_color='#000000',
        directed=True, notebook=False
    )
    net.from_nx(G)
    net.repulsion(node_distance=300, central_gravity=0.1)

    # snapshot default styles
    snapshot_js = """
    <script type="text/javascript">
      var originalNodeStyles = {};
      var originalEdgeStyles = {};
      network.body.data.nodes.get().forEach(function(n){
        originalNodeStyles[n.id] = n.color;
      });
      network.body.data.edges.get().forEach(function(e){
        originalEdgeStyles[e.id] = {
          color: e.color,
          width: e.width
        };
      });
    </script>
    """

    # write out HTML
    if output.is_dir():
        output = output / 'pyvis_graph.html'
    net.write_html(str(output), notebook=False, open_browser=False)

    # build the search box (top-left)
    search_html = """
    <div style="position:absolute; top:10px; left:10px; z-index:1000;
                background:#ffffff; padding:6px; border-radius:4px;">
      <input id="nodeSearch" placeholder="Search nodes…" style="width:180px;"/>
      <button id="clearSearch" style="margin-left:4px;">Clear</button>
    </div>
    """

    # build the legend dynamically (top-right)
    legend_items = []
    for key, cfg in STYLE.items():
        # skip edge styles
        if 'shape' not in cfg or 'color' not in cfg:
            continue

        # human‐friendly label
        label = key.replace('_', ' ').title()

        bg = cfg['color']['background']
        border = cfg['color']['border']
        bw = cfg['borderWidth']

        # circle vs square
        radius_css = 'border-radius:50%;' if cfg['shape'] == 'ellipse' else ''

        item = f"""
        <div style="margin-bottom:4px;">
          <span style="display:inline-block;
                       width:12px; height:12px;
                       background:{bg};
                       border:{bw}px solid {border};
                       margin-right:6px;
                       vertical-align:middle;
                       {radius_css}"></span>
          {label}
        </div>
        """
        legend_items.append(item)

    legend_html = f"""
    <div style="position:absolute; top:10px; right:10px; z-index:1000;
                background:#ffffff; padding:8px; border:1px solid #ccc;
                border-radius:4px; font-family:sans-serif; font-size:12px;
                line-height:1.4;">
      {''.join(legend_items)}
    </div>
    """

    # inject everything just before </body>
    snippet = f"""
    {search_html}
    {legend_html}
    {snapshot_js}
    <script type="text/javascript">
      // search
      function applyFilter() {{
        var q = document.getElementById('nodeSearch')
                    .value.trim().toLowerCase();
        network.body.data.nodes.get().forEach(function(n) {{
          var show = n.label.toLowerCase().includes(q);
          network.body.data.nodes.update({{ id: n.id, hidden: q && !show }});
        }});
      }}
      document.getElementById('nodeSearch')
        .addEventListener('input', applyFilter);
      document.getElementById('clearSearch')
        .addEventListener('click', function(){{
          document.getElementById('nodeSearch').value = '';
          network.body.data.nodes.get().forEach(function(n){{
            network.body.data.nodes.update({{id:n.id, hidden:false}});
          }});
        }});

      // static‐flow highlighting in coral red
      network.on('click', function(params) {{
        // restore defaults
        network.body.data.nodes.update(
          Object.entries(originalNodeStyles).map(function([id, color]) {{
            return {{ id: id, color: color }};
          }})
        );
        network.body.data.edges.update(
          Object.entries(originalEdgeStyles).map(function([id, style]) {{
            return {{ id: id, color: style.color, width: style.width }};
          }})
        );
        if (!params.nodes.length) return;
        var start = params.nodes[0],
            visited = new Set([start]),
            frontier = [start];
        while (frontier.length) {{
          var u = frontier.pop();
          network.getConnectedEdges(u).forEach(function(eid) {{
            var e = network.body.data.edges.get(eid);
            if (e.from === u && !visited.has(e.to)) {{
              visited.add(e.to);
              frontier.push(e.to);
            }}
          }});
        }}
        // highlight reachable
        visited.forEach(function(nid){{
          network.body.data.nodes.update({{ id: nid, color: '#FF6B6B' }});
        }});
        network.body.data.edges.get().forEach(function(e){{
          if (visited.has(e.from) && visited.has(e.to)) {{
            network.body.data.edges.update({{
              id: e.id, color: '#FF6B6B', width: 3
            }});
          }}
        }});
      }});
    </script>
    </body>
    """

    html = Path(output).read_text(encoding='utf-8')
    html = html.replace('</body>', snippet)
    Path(output).write_text(html, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(
        description="Generate file→module→function graph"
    )
    parser.add_argument(
        '--root', type=Path, default=None,
        help="Root package directory (defaults to cwd)"
    )
    parser.add_argument(
        '--output', type=Path, default=None,
        help="HTML output file or directory (defaults to root)"
    )
    parser.add_argument(
        '--debug', action='store_true', help="Enable debug logging"
    )
    args = parser.parse_args()

    root_dir = args.root.resolve() if args.root else Path.cwd().resolve()
    output   = args.output.resolve() if args.output else root_dir

    global ROOT_PKG
    ROOT_PKG = root_dir.name

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s'
    )

    logging.info(f"Scanning package: {ROOT_PKG} in {root_dir}")
    G = build_graph(root_dir)
    prune_graph(G)
    logging.info(f"Nodes={G.number_of_nodes()}, Edges={G.number_of_edges()}")
    logging.info(f"Saving graph to {output}")
    render_graph(G, output)


if __name__ == '__main__':
    main()
