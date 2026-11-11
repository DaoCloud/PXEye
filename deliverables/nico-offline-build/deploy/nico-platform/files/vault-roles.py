import base64,json,os,ssl,urllib.request
from pxeye.deployment.kubernetes import CurrentCluster
k=CurrentCluster({},'/tmp');p=os.environ['NICO_PREFIX']
def secret(n):return {key:base64.b64decode(v).decode() for key,v in k.get('secrets',n)['data'].items()}
ca=secret(p+'-nico-site-ca');recovery=json.loads(secret(p+'-nico-vault-recovery')['initialization.json'])
o=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context(cadata=ca['tls.crt'])))
for account in (os.environ.get('NICO_CORE_SERVICE_ACCOUNT') or p+'-nico-api',p+'-nico-bmc-proxy'):
 body={'bound_service_account_names':[account],'bound_service_account_namespaces':[k.namespace],'policies':['nico-core'],'ttl':'1h'}
 request=urllib.request.Request(os.environ['NICO_VAULT_URL']+'/v1/auth/kubernetes/role/'+account,data=json.dumps(body).encode(),headers={'X-Vault-Token':recovery['root_token'],'Content-Type':'application/json'},method='POST')
 with o.open(request,timeout=15) as result:assert result.status in (200,204)
print('Service-account Vault roles configured.')
