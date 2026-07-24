import json
import urllib.request

def test_contract_flow():
    # 1. Register user first (ignore 400/409 if already exists)
    try:
        reg_req = urllib.request.Request(
            'http://127.0.0.1:8000/api/auth/register',
            data=json.dumps({'email': 'hudiyavp@rknec.edu', 'password': 'Password123', 'full_name': 'vinit hudiya'}).encode(),
            headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(reg_req)
        print("User registered successfully.")
    except Exception as e:
        print("Registration note:", e)

    # 2. Login
    req = urllib.request.Request(
        'http://127.0.0.1:8000/api/auth/login',
        data=json.dumps({'email': 'hudiyavp@rknec.edu', 'password': 'Password123'}).encode(),
        headers={'Content-Type': 'application/json'}
    )
    res = urllib.request.urlopen(req)
    token = json.loads(res.read().decode())['access_token']
    print("Login successful.")

    # 3. Upload contract & test AI extraction
    boundary = '----Boundary12345'
    body_lines = [
        f'--{boundary}',
        'Content-Disposition: form-data; name="title"',
        '',
        'Master Cloud SaaS Agreement',
        f'--{boundary}',
        'Content-Disposition: form-data; name="file"; filename="contract.txt"',
        'Content-Type: text/plain',
        '',
        'This Agreement is between Acme Corp (Client) and CloudProvider LLC (Vendor). Payment terms: Net 30. SLA 99.9% uptime requirement.',
        f'--{boundary}--',
        ''
    ]
    payload = '\r\n'.join(body_lines).encode('utf-8')

    req2 = urllib.request.Request(
        'http://127.0.0.1:8000/api/contracts/',
        data=payload,
        headers={
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'Authorization': f'Bearer {token}'
        }
    )
    res2 = urllib.request.urlopen(req2)
    c = json.loads(res2.read().decode())
    
    print("\n=======================================================")
    print("SUCCESS! UPLOADED & EXTRACTED CONTRACT AI ANALYSIS:")
    print("=======================================================")
    print("Title:", c.get('title'))
    print("Contract Number:", c.get('contract_number'))
    print("Owner:", c.get('owner'))
    print("Department:", c.get('department'))
    print("Vendor:", c.get('vendor'))
    print("Client:", c.get('client'))
    print("Value:", c.get('value'), c.get('currency'))
    print("Priority:", c.get('priority'))
    print("Health Score:", c.get('health_score'), "/ 100")
    print("Risk Score:", c.get('risk_score'), "%")
    print("Missing Clauses:", c.get('missing_clauses'))
    print("Obligations:", c.get('obligations'))
    print("Payment Terms:", c.get('payment_terms'))
    print("Parties:", c.get('parties'))
    print("Auto Tags:", c.get('auto_tags'))
    print("Action Items:", c.get('action_items'))
    print("Compliance Flags:", c.get('compliance_flags'))

if __name__ == '__main__':
    test_contract_flow()
