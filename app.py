import json
import os
import subprocess
import sys
from pathlib import Path

import markdown
import nbformat
import pandas as pd
import streamlit as st
from nbclient import NotebookClient
from nbconvert import HTMLExporter

st.set_page_config(page_title="Item bank analysis", layout="wide")

# Colour shared by the title border and the body divider.
LINE_COLOR = "rgba(128, 128, 128, 0.35)"

# Folder whose contents are shown in the "tree" section (the folder itself is
# not shown).
TREE_DIR = Path(__file__).parent / "tree"


def _tree_data(folder: Path) -> list[dict]:
    """Nested list of a folder's contents: folders first, then files.

    Each file carries its path relative to TREE_DIR, which is what the tree
    sends back when the file is clicked.
    """
    try:
        entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return []
    items = []
    for entry in entries:
        if entry.is_dir():
            items.append({"name": entry.name, "children": _tree_data(entry)})
        else:
            items.append({"name": entry.name, "path": entry.relative_to(TREE_DIR).as_posix()})
    return items


# File tree for the "tree" section. Folders expand and collapse; clicking a
# file reports its path to Python as the component's "selected" state and
# fires a "clicked" trigger (which fires even when re-clicking the same file). The
# tree is only rebuilt when the folder contents change, so expanded folders
# stay open across reruns.
_FILE_TREE_JS = """
export default function (component) {
  const { data, parentElement, setStateValue, setTriggerValue } = component
  const root = parentElement.querySelector("#tree")
  if (!root) return

  const build = (items) => {
    const ul = document.createElement("ul")
    for (const item of items) {
      const li = document.createElement("li")
      if (item.children) {
        const details = document.createElement("details")
        const summary = document.createElement("summary")
        summary.textContent = item.name
        details.append(summary, build(item.children))
        li.append(details)
      } else {
        li.className = "file"
        li.textContent = item.name
        li.dataset.path = item.path
        li.title = item.name
      }
      ul.append(li)
    }
    return ul
  }

  const signature = JSON.stringify(data.items)
  if (root.dataset.signature !== signature) {
    root.replaceChildren(build(data.items))
    root.dataset.signature = signature
  }

  for (const li of root.querySelectorAll("li.file")) {
    li.classList.toggle("selected", li.dataset.path === data.selected)
  }

  root.onclick = (e) => {
    const li = e.target.closest("li.file")
    if (!li) return
    setStateValue("selected", li.dataset.path)
    setTriggerValue("clicked", li.dataset.path)
  }
}
"""

_FILE_TREE_CSS = """
#tree { font-size: 0.875rem; }
#tree ul { list-style: none; margin: 0; padding-left: 1rem; }
#tree > ul { padding-left: 0; }
#tree li { margin: 0.1rem 0; white-space: nowrap; }
#tree summary { cursor: pointer; }
#tree li.file { padding-left: 1rem; cursor: pointer; border-radius: 0.25rem; }
#tree li.file:hover { background: var(--st-secondary-background-color); }
#tree li.file.selected { color: var(--st-primary-color); }
"""

_file_tree = st.components.v2.component(
    "file_tree", html='<div id="tree"></div>', css=_FILE_TREE_CSS, js=_FILE_TREE_JS
)


def file_tree(folder: Path, *, key: str) -> tuple[str | None, bool]:
    """Show a folder's contents as a tree.

    Returns the selected file's relative path, and whether it was clicked on
    this rerun (as opposed to staying selected from an earlier click).
    """
    selected = st.session_state.get(key, {}).get("selected")
    result = _file_tree(
        data={"items": _tree_data(folder), "selected": selected},
        default={"selected": None},
        on_selected_change=lambda: None,
        on_clicked_change=lambda: None,
        key=key,
    )
    return result.selected, result.clicked is not None


# Encodings tried in order when reading files. Survey exports from Windows are
# often Windows-1252 rather than UTF-8.
ENCODINGS = ("utf-8", "cp1252")


def _is_binary(path: Path) -> bool:
    """Whether a file looks binary (e.g. PDF, Word), judged by NUL bytes near its start."""
    with path.open("rb") as f:
        return b"\x00" in f.read(8192)


def _open_externally(path: Path) -> None:
    """Open a file in the system's default app (Windows, macOS or Linux)."""
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)


# Python-Markdown extensions used to render .md files: "extra" adds tables,
# fenced code blocks, footnotes, etc.; "sane_lists" stops ordered and unordered
# lists running into each other.
MARKDOWN_EXTENSIONS = ["extra", "sane_lists"]


def show_file(path: Path, *, clicked: bool) -> None:
    """Display a file's contents: CSVs as a table, Markdown rendered, other text as plain text.

    Notebooks are run and their results shown. Files that can't be displayed
    are opened in the system's default app, but only when just clicked, so
    later reruns don't open them again.
    """
    if path.suffix.lower() == ".ipynb":
        _show_notebook(path, clicked=clicked)
        return
    if not _is_binary(path) and _show_text(path):
        return
    if clicked:
        _open_externally(path)
    st.info(f"{path.name} can't be shown here, so it was opened in its default app.")


def _run_notebook(path: Path) -> tuple[str, bool]:
    """Run every cell of a notebook, top to bottom, in a fresh kernel.

    Cells run in the notebook's own folder (as in Jupyter), so relative paths
    in the notebook work. The file itself is not changed. Returns the executed
    notebook as an HTML page, and whether any cell raised an error.
    """
    nb = nbformat.read(path, as_version=4)
    NotebookClient(
        nb,
        allow_errors=True,  # keep going and show tracebacks, as Jupyter does
        resources={"metadata": {"path": str(path.parent)}},
    ).execute()
    errored = any(
        output.get("output_type") == "error"
        for cell in nb.cells
        if cell.cell_type == "code"
        for output in cell.get("outputs", [])
    )
    html, _ = HTMLExporter(template_name="lab").from_notebook_node(nb)
    return html, errored


def _show_notebook(path: Path, *, clicked: bool) -> None:
    """Run a notebook when it's clicked and show the results.

    Results are kept in session state, so reruns of the app (e.g. dragging the
    divider) show them again without re-running the notebook. Clicking the
    notebook again runs it afresh.
    """
    runs = st.session_state.setdefault("notebook_runs", {})
    key = str(path)
    if clicked or key not in runs:
        with st.spinner(f"Running {path.name}…"):
            try:
                runs[key] = _run_notebook(path)
            except Exception as e:  # e.g. kernel failed to start, invalid notebook
                runs.pop(key, None)
                st.error(f"Could not run {path.name}: {e}")
                return
    html, errored = runs[key]
    if errored:
        st.warning("Some cells raised errors; their tracebacks are shown below.")
    # An iframe keeps the notebook's own styles from leaking into the app.
    st.iframe(html, height="stretch")


def _parse_label_value(cell: object) -> dict | None:
    """The cell's JSON object if it has exactly the properties "label" and "value"."""
    if not (isinstance(cell, str) and cell.lstrip().startswith("{")):
        return None
    try:
        obj = json.loads(cell)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) and obj.keys() == {"label", "value"} else None


@st.cache_data(show_spinner=False, max_entries=20)
def _read_csv(path: str, mtime: float, encoding: str) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Read a CSV, splitting label/value cells into two tables.

    Cells holding a {"label": ..., "value": ...} JSON object are replaced by
    their label in the first table and their value in the second; other cells
    are the same in both. If no cell holds such an object, returns the table
    as-is and None. Cached per file and modification time (mtime), so large
    files are parsed once rather than on every rerun.
    """
    df = pd.read_csv(path, encoding=encoding)
    parsed = df.map(_parse_label_value)
    is_label_value = parsed.notna()
    if not is_label_value.to_numpy().any():
        return df, None

    def pick(prop: str) -> pd.DataFrame:
        picked = parsed.map(lambda obj: obj[prop] if obj is not None else None)
        # Let columns that are now all numbers sort and align as numbers.
        return df.mask(is_label_value, picked).infer_objects()

    return pick("label"), pick("value")


def _show_csv(path: Path, encoding: str) -> None:
    """Show a CSV as a table, with a Labels/Values toggle if it has label/value cells."""
    labels, values = _read_csv(str(path), path.stat().st_mtime, encoding)
    if values is not None:
        choice = st.segmented_control(
            "Show",
            ["Labels", "Values"],
            default="Labels",
            required=True,
            key="csv_label_value",
            label_visibility="collapsed",
        )
        if choice == "Values":
            labels = values
    st.dataframe(labels, height="stretch")


def _show_text(path: Path) -> bool:
    """Show a CSV, Markdown or text file; return False if it isn't readable text."""
    suffix = path.suffix.lower()
    for encoding in ENCODINGS:
        try:
            if suffix == ".csv":
                _show_csv(path, encoding)
            elif suffix == ".md":
                text = path.read_text(encoding=encoding)
                st.html(markdown.markdown(text, extensions=MARKDOWN_EXTENSIONS))
            else:
                st.code(path.read_text(encoding=encoding), language=None)
            return True
        except UnicodeDecodeError:
            continue
        except pd.errors.ParserError as e:
            st.error(f"Could not read {path.name} as a table: {e}")
            return True
    return False


# Draggable divider for the "body" section. Streamlit has no native resizable
# split, so this component finds the body's two columns in the page and adds a
# drag handle between them. The handle lives in document.body (outside
# Streamlit's own DOM tree) so Streamlit's re-rendering never removes it.
_SPLITTER_JS = """
export default function (component) {
  const { data } = component
  const bodyKey = data.body_key
  const minPct = data.min_pct
  const maxPct = data.max_pct
  if (window.__splitPct === undefined) window.__splitPct = data.default_pct

  const findCols = () => {
    const block = document.querySelector(
      `.st-key-${bodyKey} [data-testid="stHorizontalBlock"]`
    )
    if (!block) return null
    const cols = block.querySelectorAll(':scope > [data-testid="stColumn"]')
    return cols.length >= 2 ? { block, left: cols[0], right: cols[1] } : null
  }

  let handle = document.getElementById("split-handle")
  if (!handle) {
    handle = document.createElement("div")
    handle.id = "split-handle"
    handle.innerHTML = '<div class="split-line"></div>'
    const style = document.createElement("style")
    style.textContent = `
      #split-handle { position: fixed; z-index: 999; cursor: col-resize;
        display: flex; justify-content: center; }
      #split-handle .split-line { width: 1px; height: 100%;
        background: ${data.line_color}; }
      #split-handle:hover .split-line, #split-handle.dragging .split-line {
        width: 3px; background: rgba(128, 128, 128, 0.7); }
      body.split-dragging { cursor: col-resize; user-select: none; }
    `
    document.head.appendChild(style)
    document.body.appendChild(handle)
  }

  const apply = () => {
    const els = findCols()
    if (!els) { handle.style.display = "none"; return }
    const { block, left, right } = els
    const pct = window.__splitPct
    Object.assign(left.style, {
      flex: `0 0 calc(${pct}% - 0.5rem)`,
      width: `calc(${pct}% - 0.5rem)`,
      minWidth: "0", maxWidth: "none",
    })
    Object.assign(right.style, {
      flex: "1 1 0", width: "auto", minWidth: "0", maxWidth: "none",
    })
    // Make the body exactly fill the rest of the window, so the display
    // section has a fixed height for the file contents to stretch into.
    const scroller = block.closest('[data-testid="stMain"]')
    const top = block.getBoundingClientRect().top + (scroller ? scroller.scrollTop : 0)
    const height = `${Math.max(200, window.innerHeight - top - 16)}px`
    if (block.style.height !== height) {
      // Streamlit gives the row "flex: 1 1 0%", which would override the height.
      block.style.flex = "0 0 auto"
      block.style.height = height
      block.style.minHeight = ""
    }
    const b = block.getBoundingClientRect()
    const l = left.getBoundingClientRect()
    const r = right.getBoundingClientRect()
    Object.assign(handle.style, {
      display: "flex",
      left: `${l.right}px`,
      width: `${Math.max(8, r.left - l.right)}px`,
      top: `${b.top}px`,
      height: `${b.height}px`,
    })
  }

  if (!window.__splitInit) {
    window.__splitInit = true
    let dragging = false
    handle.addEventListener("pointerdown", (e) => {
      dragging = true
      handle.setPointerCapture(e.pointerId)
      handle.classList.add("dragging")
      document.body.classList.add("split-dragging")
    })
    handle.addEventListener("pointermove", (e) => {
      if (!dragging) return
      const els = findCols()
      if (!els) return
      const b = els.block.getBoundingClientRect()
      const pct = ((e.clientX - b.left) / b.width) * 100
      window.__splitPct = Math.min(maxPct, Math.max(minPct, pct))
      apply()
    })
    const stop = () => {
      dragging = false
      handle.classList.remove("dragging")
      document.body.classList.remove("split-dragging")
    }
    handle.addEventListener("pointerup", stop)
    handle.addEventListener("pointercancel", stop)
    window.addEventListener("resize", apply)
    window.addEventListener("scroll", apply, true)
    new ResizeObserver(apply).observe(document.body)
  }
  window.__splitApply = apply
  requestAnimationFrame(apply)
}
"""

_splitter = st.components.v2.component(
    "body_splitter", html="<span></span>", js=_SPLITTER_JS
)

# Pull the page content up to just below the top of the window. The header bar
# is made transparent so it doesn't cover the title; its menu stays at top-right.
st.html(
    f"""
    <style>
      [data-testid="stMainBlockContainer"] {{ padding-top: 0rem; }}
      [data-testid="stHeader"] {{ background: transparent; }}
      .st-key-title {{ border-bottom: 1px solid {LINE_COLOR}; }}
    </style>
    """
)

# "title" section, separated from the body by a line matching the body divider.
with st.container(key="title"):
    st.title("Item bank analysis")

# "body" section, split horizontally into "tree" (left) and "display" (right).
with st.container(key="body"):
    tree, display = st.columns([1, 4], gap="small")
    with tree:
        with st.container(key="tree"):
            selected, clicked = file_tree(TREE_DIR, key="file_tree")
    with display:
        with st.container(key="display", height="stretch"):
            if selected:
                # Only show files that really are inside the tree folder.
                path = (TREE_DIR / selected).resolve()
                if path.is_file() and path.is_relative_to(TREE_DIR.resolve()):
                    show_file(path, clicked=clicked)

_splitter(
    data={"body_key": "body", "line_color": LINE_COLOR, "default_pct": 20, "min_pct": 10, "max_pct": 80},
    key="body_splitter",
)
