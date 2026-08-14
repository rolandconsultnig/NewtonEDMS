import json
import os
import urllib.parse
import urllib.request

base = 'http://localhost:8000'

# login
resp = urllib.request.urlopen(urllib.request.Request(
    base + '/api/auth/login',
    data=urllib.parse.urlencode({'username': 'admin', 'password': 'admin123'}).encode(),
    method='POST'
))
token = json.load(resp)['access_token']
print('login OK')

# me
me = json.load(urllib.request.urlopen(urllib.request.Request(
    base + '/api/auth/me', headers={'Authorization': 'Bearer ' + token})))
print('me:', me['username'], me['role'])

# folders
folders = json.load(urllib.request.urlopen(urllib.request.Request(
    base + '/api/folders', headers={'Authorization': 'Bearer ' + token})))
print('folders:', len(folders), 'root_id', folders[0]['id'] if folders else None)

# upload a small test doc
root_id = folders[0]['id']
test_path = os.path.join(os.path.dirname(__file__), 'test_hello.txt')
with open(test_path, 'w') as f:
    f.write('Hello NewEDMS')

boundary = '----WebKitFormBoundary'
body = (
    f'--{boundary}\r\n'
    f'Content-Disposition: form-data; name="folder_id"\r\n\r\n{root_id}\r\n'
    f'--{boundary}\r\n'
    f'Content-Disposition: form-data; name="title"\r\n\r\nHello Doc\r\n'
    f'--{boundary}\r\n'
    f'Content-Disposition: form-data; name="tags"\r\n\r\ndemo,test\r\n'
    f'--{boundary}\r\n'
    f'Content-Disposition: form-data; name="metadata"\r\n\r\n{{"project":"NewEDMS"}}\r\n'
    f'--{boundary}\r\n'
    f'Content-Disposition: form-data; name="file"; filename="test_hello.txt"\r\n'
    f'Content-Type: text/plain\r\n\r\n'
)
with open(test_path, 'rb') as f:
    body += f.read().decode() + '\r\n'
body += f'--{boundary}--\r\n'

req = urllib.request.Request(
    base + '/api/documents',
    data=body.encode(),
    method='POST',
    headers={
        'Authorization': 'Bearer ' + token,
        'Content-Type': f'multipart/form-data; boundary={boundary}'
    }
)
try:
    doc = json.load(urllib.request.urlopen(req))
    print('upload OK doc_id:', doc['id'], 'version:', doc['current_version'])
except urllib.error.HTTPError as e:
    print('upload failed', e.code, e.read().decode())
    raise

# search
docs = json.load(urllib.request.urlopen(urllib.request.Request(
    base + '/api/documents?search=Hello', headers={'Authorization': 'Bearer ' + token})))
print('search results:', len(docs))

# audit
logs = json.load(urllib.request.urlopen(urllib.request.Request(
    base + '/api/audit', headers={'Authorization': 'Bearer ' + token})))
print('audit entries:', len(logs))

# download
url = base + f'/api/documents/{doc["id"]}/download'
req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token})
resp = urllib.request.urlopen(req)
print('download OK bytes:', len(resp.read()))

print('ALL CHECKS PASSED')
