
#--------------------- CÓDIGO ORIENTADO A PODIO---------------------
# Paso 1: Crea una API en Python (Usando Flask)
"""
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/api/hello', methods=['GET'])
def hello():
    return jsonify({'message': 'Hello from Flask API'})

if __name__ == '__main__':
    app.run(debug=True)
"""


#Paso 3
"""
import requests

CLIENT_ID = 'TU_CLIENT_ID'
CLIENT_SECRET = 'TU_CLIENT_SECRET'

auth_url = "https://podio.com/oauth/token"
auth_data = {
    "grant_type": "client_credentials",
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET
}

response = requests.post(auth_url, data=auth_data)
token = response.json()['access_token']
print("Access Token:", token)
"""


