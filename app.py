import os
import mimetypes
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'a_very_secret_fallback_key')
csrf = CSRFProtect(app)

# --- Supabase Configuration ---
try:
    SUPABASE_URL = os.environ.get('SUPABASE_URL')
    
    # --- THIS IS THE FIX ---
    # We MUST use the SERVICE_KEY for all backend actions.
    # Your old file was using 'SUPABASE_KEY' (the anon key).
    SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')
    
    SUPABASE_BUCKET = os.environ.get('SUPABASE_BUCKET', 'product_images')
    
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise ValueError("Supabase URL and SERVICE KEY must be set in environment variables.")
        
    # Initialize the client with the powerful service key
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    
    print("Successfully connected to Supabase (using Service Role).")
except Exception as e:
    print(f"Error initializing Supabase: {e}")
    supabase = None

# --- Hardcoded manager credentials ---
ADMIN_USERNAME = 'turky'
ADMIN_PASSWORD = 'Tt123123@@'

# --- Categories ---
CATEGORIES = [
    "البطاطس",
    "البليلة",
    "الاندومي",
    "المشروبات"
]
UNCATEGORIZED = "غير مصنف"
DEFAULT_IMAGE_URL = "https://placehold.co/600x400/7838e9/ffffff?text=No+Image"

# --- Helper Functions ---
def handle_image_upload(file, current_image_path=None):
    """
    Handles file upload to Supabase Storage.
    Returns the public URL of the uploaded image or a default.
    """
    if not file or file.filename == '':
        return current_image_path or DEFAULT_IMAGE_URL

    filename = secure_filename(file.filename)
    # Get MIME type
    content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    
    try:
        # We need to read the file's bytes to upload it
        file_bytes = file.read()
        
        # Supabase storage path (e.g., "public/burger.jpg")
        # Use a 'public' folder inside the bucket
        storage_path = f"public/{filename}"
        
        # Upload the file
        # This will now work because of our SQL policies and the service key
        supabase.storage.from_(SUPABASE_BUCKET).upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"} # 'upsert' overwrites if file exists
        )
        
        # Get the public URL
        public_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(storage_path)
        return public_url
        
    except Exception as e:
        print(f"Error uploading to Supabase Storage: {e}")
        return current_image_path or DEFAULT_IMAGE_URL

# --- Public Routes ---

@app.route('/')
@app.route('/menu')
def menu():
    """Displays the public food truck menu from Supabase."""
    categories_dict = {cat: [] for cat in CATEGORIES}
    categories_dict[UNCATEGORIZED] = []

    try:
        if supabase:
            # RLS is disabled on 'products', so this public read works
            response = supabase.table('products').select('*').order('name').execute()
            products = response.data
            
            for product in products:
                # This check ensures the image path is valid before adding
                if not product.get('image_path'):
                    product['image_path'] = DEFAULT_IMAGE_URL

                category = product.get('category', UNCATEGORIZED)
                if category in categories_dict:
                    categories_dict[category].append(product)
                else:
                    categories_dict[UNCATEGORIZED].append(product)
            
            # Filter out empty categories
            visible_categories = {k: v for k, v in categories_dict.items() if v}
            
            return render_template('menu.html', categories=visible_categories, DEFAULT_IMAGE_URL=DEFAULT_IMAGE_URL)
        
    except Exception as e:
        print(f"Error fetching products from Supabase: {e}")
        flash(f"Error loading menu: {e}", 'error')
        
    return render_template('menu.html', categories={}, DEFAULT_IMAGE_URL=DEFAULT_IMAGE_URL)

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
    session.pop('logged_in', None)
    flash('تم تسجيل خروجك بنjاح.', 'info')
    return redirect(url_for('menu'))

@app.route('/admin')
def admin():
    """Shows the admin dashboard, fetching products from Supabase."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    products = []
    try:
        if supabase:
            # This works because our client uses the service_role key
            response = supabase.table('products').select('*').order('id', desc=True).execute()
            products = response.data
            for product in products:
                if not product.get('image_path'):
                    product['image_path'] = DEFAULT_IMAGE_URL
    except Exception as e:
        print(f"Error fetching products for admin: {e}")
        flash(f"Could not load products: {e}", 'error')
        
    return render_template('admin.html', products=products, categories=CATEGORIES, DEFAULT_IMAGE_URL=DEFAULT_IMAGE_URL)

@app.route('/admin/add', methods=['POST'])
def admin_add():
    """Adds a new product to the Supabase database."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    try:
        image_file = request.files.get('image_file')
        image_path = handle_image_upload(image_file) # Uploads to Supabase

        new_product = {
            'name': request.form.get('name', 'منتج جديد'),
            'price': float(request.form.get('price', '0.00')),
            'description': request.form.get('description', ''),
            'category': request.form.get('category', UNCATEGORIZED),
            'image_path': image_path
        }
        
        if supabase:
            # This works because RLS is disabled on 'products'
            supabase.table('products').insert(new_product).execute()
            flash(f"تمت إضافة المنتج '{new_product['name']}' بنجاح!", 'success')
        
    except Exception as e:
        print(f"Error adding product: {e}")
        flash(f"Error adding product: {e}", 'error')
        
    return redirect(url_for('admin'))

@app.route('/admin/edit/<int:product_id>', methods=['POST'])
def admin_edit(product_id):
    """Updates an existing product in the Supabase database."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    try:
        if supabase:
            # First, get the existing product to find its current image path
            response = supabase.table('products').select('image_path').eq('id', product_id).single().execute()
            current_image = response.data.get('image_path') if response.data else DEFAULT_IMAGE_URL
            
            # Handle image upload
            image_file = request.files.get('image_file')
            image_path = handle_image_upload(image_file, current_image) # Pass current image as fallback

            product_update = {
                'name': request.form.get('name'),
                'price': float(request.form.get('price')),
                'description': request.form.get('description', ''),
                'category': request.form.get('category', UNCATEGORIZED),
                'image_path': image_path # This will be the new URL or the old one
            }

            # This works because RLS is disabled on 'products'
            supabase.table('products').update(product_update).eq('id', product_id).execute()
            flash(f"تم تعديل المنتج '{product_update['name']}' بنjاح!", 'success')

    except Exception as e:
        print(f"Error editing product: {e}")
        flash(f"Error editing product: {e}", 'error')
        
    return redirect(url_for('admin'))

@app.route('/admin/delete/<int:product_id>')
def admin_delete(product_id):
    """Deletes a product from the Supabase database."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    try:
        if supabase:
            # We don't need to delete the image from storage,
            # but you could add that logic here if you want.
            # This works because RLS is disabled on 'products'
            supabase.table('products').delete().eq('id', product_id).execute()
            flash(f"تم حذف المنتج بنجاح!", 'success')
            
    except Exception as e:
        print(f"Error deleting product: {e}")
        flash(f"Error deleting product: {e}", 'error')
        
    return redirect(url_for('admin'))

# --- Main Run ---
if __name__ == '__main__':
    # This block is for LOCAL development (e.g., running 'python app.py')
    # It runs a simple, non-production server.
    print("Starting Flask app in debug mode for local development...")
    app.run(debug=True, port=5000)