
#--------------------- CÓDIGO ORIENTADO A PODIO---------------------

from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/api/hello', methods=['GET'])
def hello():
    return jsonify({'message': 'Hello from Flask API'})

if __name__ == '__main__':
    app.run(debug=True)



import requests

CLIENT_ID = 'gqm-admin-panel'
CLIENT_SECRET = '7F788pt1ai4W1bWw4K43MSC0JZp8xdwR7uoNFRho2ahvBhEivSvv67z7bdqP4kce'

auth_url = "https://podio.com/oauth/token"
auth_data = {
    "grant_type": "client_credentials",
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET
}

response = requests.post(auth_url, data=auth_data)
token = response.json()['access_token']
print("Access Token:", token)
