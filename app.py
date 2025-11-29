import os
import mimetypes
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename
from supabase import create_client, Client
from dotenv import load_dotenv

# 1. LOAD .env FILE
load_dotenv() 

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'a_very_secret_fallback_key')
csrf = CSRFProtect(app)

# --- Supabase Configuration ---
try:
    SUPABASE_URL = os.environ.get('SUPABASE_URL')
    SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY') 
    SUPABASE_BUCKET = os.environ.get('SUPABASE_BUCKET', 'product_images')
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Supabase URL and SERVICE KEY must be set in environment variables.")
        
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Successfully connected to Supabase.")
except Exception as e:
    print(f"Error initializing Supabase: {e}")
    supabase = None

# --- Hardcoded manager credentials ---
ADMIN_USERNAME = 'turky'
ADMIN_PASSWORD = 'Tt123123@@'

UNCATEGORIZED = "غير مصنف"
DEFAULT_IMAGE_URL = "https://placehold.co/600x400/7838e9/ffffff?text=No+Image"

# --- Helper Functions ---
def get_categories():
    """Fetches categories from DB sorted by sort_order."""
    try:
        if supabase:
            response = supabase.table('categories').select('*').order('sort_order').execute()
            # Return list of names
            return response.data # returns [{'id':1, 'name': '...', 'sort_order': 10}, ...]
    except Exception as e:
        print(f"Error fetching categories: {e}")
    return []

def handle_image_upload(file, current_image_path=None):
    """Handles file upload to Supabase Storage."""
    if not file or file.filename == '':
        return current_image_path or DEFAULT_IMAGE_URL

    filename = secure_filename(file.filename)
    content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    
    try:
        file_bytes = file.read()
        storage_path = f"{os.urandom(8).hex()}_{filename}"
        
        supabase.storage.from_(SUPABASE_BUCKET).upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "false"} 
        )
        return supabase.storage.from_(SUPABASE_BUCKET).get_public_url(storage_path)
        
    except Exception as e:
        print(f"Error uploading to Supabase Storage: {e}")
        return current_image_path or DEFAULT_IMAGE_URL

# --- Public Routes ---

@app.route('/')
@app.route('/menu')
def menu():
    """Displays the public food truck menu from Supabase."""
    
    # 1. Fetch Categories from DB
    db_categories = get_categories()
    
    # 2. Build Dictionary ordered by the DB sort_order
    categories_dict = {}
    for cat in db_categories:
        categories_dict[cat['name']] = []
    
    categories_dict[UNCATEGORIZED] = []

    try:
        if supabase:
            # Fetch all products
            response = supabase.table('products').select('*').order('name').execute()
            products = response.data
            
            for product in products:
                category = product.get('category', UNCATEGORIZED)
                if category in categories_dict:
                    categories_dict[category].append(product)
                else:
                    # If product has a category that was deleted from DB, put in Uncategorized
                    categories_dict[UNCATEGORIZED].append(product)
            
            # Filter out empty categories
            visible_categories = {k: v for k, v in categories_dict.items() if v}
            
            return render_template('menu.html', categories=visible_categories, DEFAULT_IMAGE_URL=DEFAULT_IMAGE_URL)
        
    except Exception as e:
        print(f"Error fetching products: {e}")
        flash(f"Error loading menu: {e}", 'error')
        
    return render_template('menu.html', categories={}, DEFAULT_IMAGE_URL=DEFAULT_IMAGE_URL)

# --- Admin & Auth Routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin'))
        else:
            error = 'بيانات الدخول غير صحيحة.'
    
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('تم تسجيل الخروج.', 'info')
    return redirect(url_for('menu'))

@app.route('/admin')
def admin():
    """Shows the admin dashboard."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    products = []
    categories_data = []
    
    try:
        if supabase:
            # Fetch products
            prod_response = supabase.table('products').select('*').order('id', desc=True).execute()
            products = prod_response.data
            
            # Fetch categories (Full object with ID and Order)
            categories_data = get_categories()

    except Exception as e:
        print(f"Error fetching data: {e}")
        flash(f"Could not load data: {e}", 'error')
    
    # Extract just names for the dropdown
    category_names = [c['name'] for c in categories_data]
        
    return render_template('admin.html', 
                           products=products, 
                           categories=category_names, # For the dropdown in Add/Edit Product
                           all_categories=categories_data, # For the Manage Categories section
                           DEFAULT_IMAGE_URL=DEFAULT_IMAGE_URL)

@app.route('/admin/add', methods=['POST'])
def admin_add():
    if not session.get('logged_in'): return redirect(url_for('login'))

    try:
        image_file = request.files.get('image_file')
        image_path = handle_image_upload(image_file)

        new_product = {
            'name': request.form.get('name', 'منتج جديد'),
            'price': float(request.form.get('price', '0.00')),
            'description': request.form.get('description', ''),
            'category': request.form.get('category', UNCATEGORIZED),
            'image_path': image_path
        }
        
        if supabase:
            supabase.table('products').insert(new_product).execute()
            flash('تمت الإضافة بنجاح', 'success')
        
    except Exception as e:
        flash(f"Error: {e}", 'error')
        
    return redirect(url_for('admin'))

@app.route('/admin/edit/<int:product_id>', methods=['POST'])
def admin_edit(product_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    try:
        if supabase:
            response = supabase.table('products').select('image_path').eq('id', product_id).single().execute()
            current_image = response.data.get('image_path') if response.data else DEFAULT_IMAGE_URL
            
            image_file = request.files.get('image_file')
            image_path = handle_image_upload(image_file, current_image)

            product_update = {
                'name': request.form.get('name'),
                'price': float(request.form.get('price')),
                'description': request.form.get('description', ''),
                'category': request.form.get('category', UNCATEGORIZED),
                'image_path': image_path
            }

            supabase.table('products').update(product_update).eq('id', product_id).execute()
            flash('تم التعديل بنجاح', 'success')

    except Exception as e:
        flash(f"Error: {e}", 'error')
        
    return redirect(url_for('admin'))

@app.route('/admin/delete/<int:product_id>')
def admin_delete(product_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    try:
        if supabase:
            supabase.table('products').delete().eq('id', product_id).execute()
            flash('تم الحذف بنجاح', 'success')
    except Exception as e:
        flash(f"Error: {e}", 'error')
    return redirect(url_for('admin'))

# --- NEW: Category Management Routes ---

@app.route('/admin/category/add', methods=['POST'])
def add_category():
    if not session.get('logged_in'): return redirect(url_for('login'))
    try:
        name = request.form.get('cat_name')
        order = request.form.get('cat_order', 0)
        if supabase and name:
            supabase.table('categories').insert({'name': name, 'sort_order': order}).execute()
            flash('تم إضافة القسم بنجاح', 'success')
    except Exception as e:
        flash(f"خطأ في إضافة القسم: {e}", 'error')
    return redirect(url_for('admin'))

@app.route('/admin/category/update', methods=['POST'])
def update_categories():
    """Updates the sort order of a category"""
    if not session.get('logged_in'): return redirect(url_for('login'))
    try:
        cat_id = request.form.get('cat_id')
        cat_order = request.form.get('cat_order')
        
        if supabase and cat_id:
            supabase.table('categories').update({'sort_order': cat_order}).eq('id', cat_id).execute()
            flash('تم تحديث الترتيب', 'success')
    except Exception as e:
        flash(f"Error: {e}", 'error')
    return redirect(url_for('admin'))

@app.route('/admin/category/delete/<int:cat_id>')
def delete_category(cat_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    try:
        if supabase:
            # Optional: Check if products exist in this category before deleting?
            # For now, we just delete. Products will become "Uncategorized" automatically in menu logic.
            supabase.table('categories').delete().eq('id', cat_id).execute()
            flash('تم حذف القسم', 'success')
    except Exception as e:
        flash(f"Error: {e}", 'error')
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)