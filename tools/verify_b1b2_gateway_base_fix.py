"""Read-only regression checks for AUGMIS runtime gateway HTML rewrite."""
from pathlib import Path
import ast
import argparse
import re
from urllib.parse import urljoin

PATH = Path('services/api/app/routes/instances.py')

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', default='.')
    args = p.parse_args()
    source = (Path(args.repo)/PATH).read_text(encoding='utf-8')
    tree = ast.parse(source)
    target = next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='_rewrite_gateway_html')
    snippet=ast.Module(body=[target],type_ignores=[])
    ns={'re':re}
    exec(compile(snippet,str(PATH),'exec'),ns)
    rewrite=ns['_rewrite_gateway_html']
    gateway='/api/v1/runtime-gateway/TestID_9/'
    inp=b'<html><head><link href="style.css"><script src="app.js"></script><img src="/images/logo.png"><a href="https://example.com/x">ext</a><img src="//cdn.example.net/a.png"></head></html>'
    out=rewrite(payload=inp,gateway_base=gateway).decode()
    assert out.count('<base href="'+gateway+'">')==1, out
    assert gateway+'api/v1/runtime-gateway' not in out, out
    assert '<img src="'+gateway+'images/logo.png">' in out, out
    assert '<img src="//cdn.example.net/a.png">' in out, out
    assert 'href="https://example.com/x"' in out, out
    assert urljoin('http://127.0.0.1:8001'+gateway,'style.css')=='http://127.0.0.1:8001'+gateway+'style.css'
    # Existing explicit base is left intact.
    explicit=b'<html><head><base href="https://example.org/assets/"><script src="app.js"></script></head></html>'
    assert rewrite(payload=explicit,gateway_base=gateway).decode().count('<base ')==1
    # Root-relative CSS asset URLs retain one gateway prefix.
    css=b'<html><head><style>.x{background:url(/images/a.png)}</style></head></html>'
    res=rewrite(payload=css,gateway_base=gateway).decode()
    assert 'url('+gateway+'images/a.png)' in res, res
    assert gateway+'api/v1/runtime-gateway' not in res,res
    print('[PASS] base href insertion occurs after URL rewriting')
    print('[PASS] relative assets, root assets, CSS URLs, protocol-relative URLs')
    print('[PASS] existing explicit base not duplicated; no double gateway prefix')

if __name__=='__main__':
    main()
