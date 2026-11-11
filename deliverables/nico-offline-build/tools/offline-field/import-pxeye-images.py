#!/usr/bin/env python3
"""Import only the two locked PXEye OCI archives; refuse unknown tag replacement."""
import argparse
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--bundle',required=True,type=Path);p.add_argument('--registry-url',required=True)
p.add_argument('--insecure',action='store_true')
a=p.parse_args();root=a.bundle.resolve();url=a.registry_url.rstrip('/');parsed=urllib.parse.urlsplit(url)
assert parsed.scheme in ('http','https') and parsed.netloc and not parsed.path and not parsed.username and not parsed.query and not parsed.fragment,'Use http(s)://host:port'
assert shutil.which('skopeo'),'skopeo must be installed on the import machine'
rows=json.loads((root/'manifests/deployment-images-lock.json').read_text())
context=ssl._create_unverified_context() if a.insecure else ssl.create_default_context()
# This profile uses a no-auth registry. Authentication challenges fail closed.
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
for row in rows:
    ref=row['image'].split('/',1)[1];repo,tag=ref.rsplit(':',1)
    def digest():
        request=urllib.request.Request(url+'/v2/'+repo+'/manifests/'+tag,method='HEAD',headers={'Accept':'application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'})
        try:
            with opener.open(request,timeout=20) as response:return response.headers.get('Docker-Content-Digest')
        except urllib.error.HTTPError as error:
            if error.code==404:return None
            raise SystemExit('Registry HEAD failed: '+str(error.code)) from None
    old=digest()
    if old is not None:
        assert old==row['digest'],'Existing tag has a different digest; stopped: '+ref
        print('ALREADY_LOCKED',ref);continue
    archive=(root/row['archive']).resolve();assert archive.is_relative_to(root) and archive.is_file()
    command=['skopeo','copy','--preserve-digests','--dest-oci-accept-uncompressed-layers']
    if a.insecure or parsed.scheme=='http':command+=['--dest-tls-verify=false']
    command+=['oci-archive:'+str(archive)+':'+row['source_image'],'docker://'+parsed.netloc+'/'+ref]
    result=subprocess.run(command,capture_output=True,text=True,timeout=1800)
    assert result.returncode==0,'skopeo failed (stderr withheld to protect authentication details): '+str(result.returncode)
    assert digest()==row['digest'],'Uploaded digest mismatch: '+ref
    print('IMPORTED_LOCKED',ref)
