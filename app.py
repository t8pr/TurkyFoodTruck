import json
import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename

app = Flask(__name__)
# You MUST change this secret key for production
app.secret_key = 'your_very_secret_random_key_here'
# Initialize CSRF protection
csrf = CSRFProtect(app)

# --- Configuration ---
PRODUCTS_FILE = 'products.json'
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Hardcoded manager credentials
ADMIN_USERNAME = 'turky'
ADMIN_PASSWORD = 'Tt123123@@'

# --- Categories ---
# These are the categories you want.
CATEGORIES = [
    "البطاطس",
    "البليلة",
    "الاندومي",
    "المشروبات"
]
UNCATEGORIZED = "غير مصنف"

# --- Helper Functions ---

def allowed_file(filename):
    """Checks if the file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_products():
    """Loads products from the JSON file."""
    if not os.path.exists(PRODUCTS_FILE):
        return []
    try:
        # Read with UTF-8 encoding for Arabic characters
        with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

def save_products(products):
    """Saves the products list to the JSON file."""
    # Write with UTF-8 encoding
    with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(products, f, indent=2, ensure_ascii=False)

def get_next_id(products):
    """Calculates the next available product ID."""
    if not products:
        return 1
    return max(product.get('id', 0) for product in products) + 1

# --- Public Routes ---

@app.route('/')
@app.route('/menu')
def menu():
    """Displays the public food truck menu."""
    products = load_products()
    
    # Group products by category for the new menu layout
    categories_dict = {cat: [] for cat in CATEGORIES}
    categories_dict[UNCATEGORIZED] = [] # For products with no category

    for product in products:
        category = product.get('category', UNCATEGORIZED)
        if category in categories_dict:
            categories_dict[category].append(product)
        else:
            # If a product has an old/unknown category, add it to 'uncategorized'
            categories_dict[UNCATEGORIZED].append(product)
            
    # --- *** CHANGE *** ---
    # Filter out empty categories so they don't show on the menu
    visible_categories = {}
    for category, cat_products in categories_dict.items():
        if cat_products:  # This checks if the list is not empty
            visible_categories[category] = cat_products
            
    # Now, pass the *filtered* dictionary to the template
    return render_template('menu.html', categories=visible_categories)

# --- Admin & Auth Routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles manager login."""
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin'))
        else:
            error = 'اسم المستخدم أو كلمة المرور غير صحيحة. يرجى المحاولة مرة أخرى.'
    
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    """Logs the manager out."""
    session.pop('logged_in', None)
    flash('تم تسجيل خروجك بنجاح.', 'info')
    return redirect(url_for('menu'))

@app.route('/admin')
def admin():
    """Displays the admin dashboard for managing products."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    products = load_products()
    # Pass the categories to the template for the dropdowns
    return render_template('admin.html', products=products, categories=CATEGORIES)

def handle_image_upload(file, current_image_path=None):
    """Handles saving a new image file and returns its path."""
    placeholder_path = "https://placehold.co/600x400/7838e9/fff?text=Image"
    
    if not file or file.filename == '':
        # No new file uploaded, keep the old one or use placeholder if it's a new product
        return current_image_path or placeholder_path

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # Ensure the uploads directory exists
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # We save the relative path for use in url_for('static', ...)
        return 'uploads/' + filename
    
    # Fallback in case of disallowed file type or other error
    return current_image_path or placeholder_path

@app.route('/admin/add', methods=['POST'])
def admin_add():
    """Adds a new product."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    products = load_products()
    
    # Handle the file upload
    image_file = request.files.get('image_file')
    image_path = handle_image_upload(image_file)

    new_product = {
        'id': get_next_id(products),
        'name': request.form.get('name', 'منتج جديد'),
        'price': request.form.get('price', '0.00'),
        'description': request.form.get('description', ''),
        'category': request.form.get('category', UNCATEGORIZED),
        'image_path': image_path  # Changed from image_url
    }
    
    products.append(new_product)
    save_products(products)
    
    flash(f"تمت إضافة المنتج '{new_product['name']}' بنجاح!", 'success')
    return redirect(url_for('admin'))

@app.route('/admin/edit/<int:product_id>', methods=['POST'])
def admin_edit(product_id):
    """Updates an existing product."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    products = load_products()
    product_to_update = None
    for product in products:
        if product.get('id') == product_id:
            product_to_update = product
            break
    
    if product_to_update:
        # Get data from form
        product_to_update['name'] = request.form.get('name', product_to_update['name'])
        product_to_update['price'] = request.form.get('price', product_to_update['price'])
        product_to_update['description'] = request.form.get('description', product_to_update['description'])
        product_to_update['category'] = request.form.get('category', product_to_update.get('category', UNCATEGORIZED))

        # Handle image upload for editing
        image_file = request.files.get('image_file')
        if image_file and image_file.filename != '':
            # Only update image if a *new* file is provided
            current_image = product_to_update.get('image_path')
            product_to_update['image_path'] = handle_image_upload(image_file, current_image)
            # You could add logic here to delete the old image if it's not a placeholder
            
        save_products(products)
        flash(f"تم تعديل المنتج '{product_to_update['name']}' بنجاح!", 'success')
    else:
        flash(f"لم يتم العثور على المنتج بالتصنيف {product_id}.", 'error')
    
    return redirect(url_for('admin'))

@app.route('/admin/delete/<int:product_id>')
def admin_delete(product_id):
    """Deletes a product."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    products = load_products()
    product_to_delete = next((p for p in products if p.get('id') == product_id), None)
    
    if product_to_delete:
        products_to_keep = [p for p in products if p.get('id') != product_id]
        save_products(products_to_keep)
        
        # Optional: Delete the image file from disk
        # image_path = product_to_delete.get('image_path')
        # if image_path and image_path.startswith('uploads/'):
        #     try:
        #         os.remove(os.path.join(app.config['UPLOAD_FOLDER'], image_path.split('/')[1]))
        #     except OSError:
        #         pass # Failed to delete, but not critical
                
        flash(f"تم حذف المنتج '{product_to_delete['name']}' بنجاح!", 'success')
    else:
        flash(f"لم يتم العثور على المنتج بالتصنيف {product_id} لحذفه.", 'error')
    
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(debug=True)