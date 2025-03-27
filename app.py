from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from gradio_client import Client, handle_file
from werkzeug.utils import secure_filename
import os
from datetime import datetime
from flask_jwt_extended import JWTManager, jwt_required, create_access_token
import secrets
from flasgger import Swagger

# Initialisation de l'application Flask
app = Flask(__name__)

# Generate a secure secret key
app.config['JWT_SECRET_KEY'] = secrets.token_hex(16)
jwt = JWTManager(app)

app.config['SWAGGER'] = {'title': 'Image Processing API', 'uiversion': 3}
Swagger(app)

# Configuration de la base de données SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///images.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialisation de la base de données
db = SQLAlchemy(app)

# Modèle de données
class ImageProcessing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(255), nullable=False)
    text_result = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'image_path': self.image_path,
            'text_result': self.text_result,
            'created_at': self.created_at.isoformat()
        }

# Créer les tables dans la base de données
with app.app_context():
    db.create_all()

# Routes de l'API

# Route pour login
@app.route('/login', methods=['POST'])
def login():
    """
    Authentifie un utilisateur et retourne un token JWT.
    ---
    tags:
      - Authentication
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            username:
              type: string
              description: Nom d'utilisateur
            password:
              type: string
              description: Mot de passe
    responses:
      200:
        description: Token JWT généré avec succès
        schema:
          type: object
          properties:
            access_token:
              type: string
      401:
        description: Identifiants invalides
    """
    username = request.json.get('username')
    password = request.json.get('password')
    if username == 'admin' and password == 'password':  # Exemple simple
        token = create_access_token(identity=username)
        return jsonify({'access_token': token})
    return jsonify({'error': 'Invalid credentials'}), 401

# GET - Lister toutes les images
@app.route('/api/images', methods=['GET'])
@jwt_required()
def get_images():
    """
    Récupère la liste de toutes les images traitées.
    ---
    tags:
      - Images
    security:
      - JWT: []
    responses:
      200:
        description: Liste des images avec leurs résultats
        schema:
          type: array
          items:
            type: object
            properties:
              id:
                type: integer
              image_path:
                type: string
              text_result:
                type: string
              created_at:
                type: string
                format: date-time
    """
    images = ImageProcessing.query.all()
    return jsonify([image.to_dict() for image in images])

# POST - Créer une nouvelle entrée avec OCR
@app.route('/api/images', methods=['POST'])
@jwt_required()
def create_image():
    """
    Crée une nouvelle entrée d'image et effectue l'OCR.
    ---
    tags:
      - Images
    parameters:
      - in: formData
        name: image
        type: file
        required: true
        description: Fichier image à traiter
      - in: formData
        name: prompt
        type: string
        required: false
        description: Prompt optionnel pour l'OCR
    responses:
      201:
        description: Image créée avec succès
        schema:
          type: object
          properties:
            id:
              type: integer
            image_path:
              type: string
            text_result:
              type: string
            created_at:
              type: string
              format: date-time
      400:
        description: Erreur de validation
    """
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400
    
    image_file = request.files['image']
    if image_file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    filename = secure_filename(image_file.filename)
    image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    image_file.save(image_path)

    # Appel au client Gradio pour OCR
    client = Client("prithivMLmods/Multimodal-OCR")
    prompt = request.form.get('prompt', '')
    result = client.predict(
        message={"text": prompt, "files": [handle_file(image_path)]},
        api_name="/chat"
    )

    # Sauvegarder dans la base de données
    new_image = ImageProcessing(image_path=image_path, text_result=result)
    db.session.add(new_image)
    db.session.commit()

    return jsonify(new_image.to_dict()), 201

# GET - Récupérer une image spécifique
@app.route('/api/images/<int:id>', methods=['GET'])
@jwt_required()
def get_image(id):
    """
    Récupère une image spécifique par son ID.
    ---
    tags:
      - Images
    security:
      - JWT: []
    parameters:
      - in: path
        name: id
        type: integer
        required: true
        description: ID de l'image
    responses:
      200:
        description: Détails de l'image
        schema:
          type: object
          properties:
            id:
              type: integer
            image_path:
              type: string
            text_result:
              type: string
            created_at:
              type: string
              format: date-time
      404:
        description: Image non trouvée
    """
    image = ImageProcessing.query.get_or_404(id)
    return jsonify(image.to_dict())

# PUT - Mettre à jour une image
@app.route('/api/images/<int:id>', methods=['PUT'])
@jwt_required()
def update_image(id):
    """
    Met à jour une image existante et/ou son résultat OCR.
    ---
    tags:
      - Images
    security:
      - JWT: []
    parameters:
      - in: path
        name: id
        type: integer
        required: true
        description: ID de l'image
      - in: formData
        name: image
        type: file
        required: false
        description: Nouvelle image (optionnel)
      - in: formData
        name: prompt
        type: string
        required: false
        description: Nouveau prompt pour l'OCR
    responses:
      200:
        description: Image mise à jour avec succès
        schema:
          type: object
          properties:
            id:
              type: integer
            image_path:
              type: string
            text_result:
              type: string
            created_at:
              type: string
              format: date-time
      404:
        description: Image non trouvée
    """
    image = ImageProcessing.query.get_or_404(id)

    if 'image' in request.files:
        image_file = request.files['image']
        filename = secure_filename(image_file.filename)
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        image_file.save(image_path)
        image.image_path = image_path
    
    if 'prompt' in request.form:
        client = Client("prithivMLmods/Multimodal-OCR")
        result = client.predict(
            message={"text": request.form['prompt'], "files": [handle_file(image.image_path)]},
            api_name="/chat"
        )
        image.text_result = result

    db.session.commit()
    return jsonify(image.to_dict())

# DELETE - Supprimer une image
@app.route('/api/images/<int:id>', methods=['DELETE'])
def delete_image(id):
    """
    Supprime une image et ses données associées.
    ---
    tags:
      - Images
    security:
      - JWT: []
    parameters:
      - in: path
        name: id
        type: integer
        required: true
        description: ID de l'image à supprimer
    responses:
      204:
        description: Image supprimée avec succès
      404:
        description: Image non trouvée
    """
    image = ImageProcessing.query.get_or_404(id)
    if os.path.exists(image.image_path):
        os.remove(image.image_path)
    db.session.delete(image)
    db.session.commit()
    return '', 204

# Lancer l'application
if __name__ == '__main__':
    app.run(debug=True)