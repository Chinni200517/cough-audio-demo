"""Execute notebook Python cells and save fresh outputs without a Jupyter server."""
import contextlib
import io
import json
import os
from pathlib import Path
import traceback

os.environ['MPLBACKEND'] = 'Agg'
ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / 'run_results'

def main():
    RESULTS.mkdir(exist_ok=True)
    statuses = {}
    for path in sorted(ROOT.glob('*.ipynb')):
        notebook = json.loads(path.read_text(encoding='utf-8'))
        namespace = {'__name__': '__main__'}
        log = io.StringIO()
        status = 'passed'
        for index, cell in enumerate(notebook['cells']):
            if cell['cell_type'] != 'code':
                continue
            output = io.StringIO()
            try:
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    exec(compile(''.join(cell['source']), f'{path.name}:cell{index}', 'exec'), namespace)
            except Exception:
                traceback.print_exc(file=output)
                status = f'failed at cell {index}'
            cell['execution_count'] = index + 1
            cell['outputs'] = [{'output_type': 'stream', 'name': 'stdout', 'text': output.getvalue().splitlines(True)}]
            log.write(output.getvalue())
            if status != 'passed':
                break
        (RESULTS / path.name).write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding='utf-8')
        (RESULTS / (path.stem + '.txt')).write_text(log.getvalue(), encoding='utf-8')
        statuses[path.name] = status
        print(path.name, status, flush=True)
    (RESULTS / 'notebook_status.json').write_text(json.dumps(statuses, indent=2), encoding='utf-8')

if __name__ == '__main__':
    main()
