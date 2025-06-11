from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_mysqldb import MySQL
import MySQLdb.cursors
import bcrypt
import os
import secrets
import re
from werkzeug.utils import secure_filename
# from flask_ngrok import run_with_ngrok
app = Flask(__name__)
# run_with_ngrok(app)
# app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(16))

# MySQL configurations
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = '19062004@khuoch'
app.config['MYSQL_DB'] = 'MySystem'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
mysql = MySQL(app)

# File upload configurations
UPLOAD_FOLDER = 'static/image'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Input validation regex
USERNAME_REGEX = r'^[a-zA-Z0-9_]{3,50}$'
EMAIL_REGEX = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Decorator to restrict access to admin-only routes
def admin_required(f):
    def wrap(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Access denied. Admin privileges required.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

# Home route
@app.route('/')
def index():
    return redirect(url_for('products'))

# User: Product listing
@app.route('/products')
def products():
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM Products")
    products = cur.fetchall()
    cur.close()
    return render_template('user/products.html', products=products)

# User: Product search
@app.route('/products/search', methods=['GET'])
def product_search():
    query = request.args.get('query', '').strip()
    if not query:
        flash('Please enter a search term.', 'danger')
        return redirect(url_for('products'))
    
    query = query.replace('%', r'\%').replace('_', r'\_')
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT * FROM Products 
        WHERE product_name LIKE %s OR category LIKE %s
    """, (f'%{query}%', f'%{query}%'))
    products = cur.fetchall()
    cur.close()
    if not products:
        flash('No products found.', 'danger')
    return render_template('user/products.html', products=products, search_query=query)

# User: Product details
@app.route('/product/<int:product_id>')
def product_details(product_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM Products WHERE product_id = %s", (product_id,))
    product = cur.fetchone()
    cur.close()
    if not product:
        flash('Product not found.', 'danger')
        return redirect(url_for('products'))
    return render_template('user/product_details.html', product=product)

# User: Add to cart
@app.route('/cart/add/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    if 'user_id' not in session:
        flash('Please log in to add items to cart.', 'danger')
        return redirect(url_for('login'))
    
    try:
        quantity = int(request.form.get('quantity', 1))
        if quantity <= 0:
            raise ValueError("Quantity must be positive.")
    except ValueError:
        flash('Invalid quantity.', 'danger')
        return redirect(url_for('product_details', product_id=product_id))
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM Products WHERE product_id = %s", (product_id,))
    product = cur.fetchone()
    
    if not product:
        flash('Product not found.', 'danger')
        cur.close()
        return redirect(url_for('products'))
    
    if product['stock_quantity'] < quantity:
        flash(f'Only {product["stock_quantity"]} items available in stock.', 'danger')
        cur.close()
        return redirect(url_for('product_details', product_id=product_id))
    
    cur.execute("SELECT cart_item_id, quantity FROM Cart_Items WHERE user_id = %s AND product_id = %s",
                (session['user_id'], product_id))
    existing_item = cur.fetchone()
    if existing_item:
        new_quantity = existing_item['quantity'] + quantity
        if new_quantity > product['stock_quantity']:
            flash(f'Cannot add {new_quantity} items. Only {product["stock_quantity"]} available.', 'danger')
            cur.close()
            return redirect(url_for('product_details', product_id=product_id))
        cur.execute("UPDATE Cart_Items SET quantity = %s WHERE cart_item_id = %s",
                    (new_quantity, existing_item['cart_item_id']))
    else:
        cur.execute("INSERT INTO Cart_Items (user_id, product_id, quantity) VALUES (%s, %s, %s)",
                    (session['user_id'], product_id, quantity))
    
    mysql.connection.commit()
    cur.close()
    flash('Product added to cart!', 'success')
    return redirect(url_for('cart'))

# User: Cart
@app.route('/cart')
def cart():
    if 'user_id' not in session:
        flash('Please log in to view your cart.', 'danger')
        return redirect(url_for('login'))
    
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT ci.cart_item_id, p.product_id, p.product_name, p.price, ci.quantity, p.image
        FROM Cart_Items ci
        JOIN Products p ON ci.product_id = p.product_id
        WHERE ci.user_id = %s
    """, (session['user_id'],))
    cart_items = cur.fetchall()
    cur.close()
    total = sum(item['price'] * item['quantity'] for item in cart_items)
    return render_template('user/cart.html', cart_items=cart_items, total=total)

# User: Checkout
@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if 'user_id' not in session:
        flash('Please log in to checkout.', 'danger')
        return redirect(url_for('login'))
    
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT ci.cart_item_id, p.product_id, p.product_name, p.price, ci.quantity, p.stock_quantity
        FROM Cart_Items ci
        JOIN Products p ON ci.product_id = p.product_id
        WHERE ci.user_id = %s
    """, (session['user_id'],))
    cart_items = cur.fetchall()
    
    if not cart_items:
        flash('Your cart is empty.', 'danger')
        cur.close()
        return redirect(url_for('cart'))
    
    if request.method == 'POST':
        for item in cart_items:
            if item['quantity'] > item['stock_quantity']:
                flash(f'Not enough stock for {item["product_name"]}. Only {item["stock_quantity"]} available.', 'danger')
                cur.close()
                return redirect(url_for('cart'))
        
        cur.execute("SELECT customer_id FROM Users WHERE user_id = %s", (session['user_id'],))
        customer = cur.fetchone()
        if not customer:
            flash('User not found.', 'danger')
            cur.close()
            return redirect(url_for('login'))
        customer_id = customer['customer_id']
        
        cur.execute("SELECT staff_id FROM Staff WHERE role = 'Sales Assistant' LIMIT 1")
        staff = cur.fetchone()
        if not staff:
            flash('No staff available to process order.', 'danger')
            cur.close()
            return redirect(url_for('cart'))
        staff_id = staff['staff_id']
        
        total_amount = sum(item['price'] * item['quantity'] for item in cart_items)
        
        cur.execute("""
            INSERT INTO Orders (customer_id, staff_id, order_date, total_amount)
            VALUES (%s, %s, CURDATE(), %s)
        """, (customer_id, staff_id, total_amount))
        order_id = cur.lastrowid
        
        for item in cart_items:
            cur.execute("""
                INSERT INTO Order_Items (order_id, product_id, quantity, price)
                VALUES (%s, %s, %s, %s)
            """, (order_id, item['product_id'], item['quantity'], item['price']))
            cur.execute("UPDATE Products SET stock_quantity = stock_quantity - %s WHERE product_id = %s",
                        (item['quantity'], item['product_id']))
        
        cur.execute("DELETE FROM Cart_Items WHERE user_id = %s", (session['user_id'],))
        mysql.connection.commit()
        cur.close()
        flash('Order placed successfully!', 'success')
        return redirect(url_for('order_confirmation', order_id=order_id))
    
    total = sum(item['price'] * item['quantity'] for item in cart_items)
    cur.close()
    return render_template('user/checkout.html', cart_items=cart_items, total=total)

# User: Order confirmation
@app.route('/order_confirmation/<int:order_id>')
def order_confirmation(order_id):
    if 'user_id' not in session:
        flash('Please log in to view order confirmation.', 'danger')
        return redirect(url_for('login'))
    
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT o.order_id, o.order_date, o.total_amount, c.full_name
        FROM Orders o
        JOIN Customers c ON o.customer_id = c.customer_id
        WHERE o.order_id = %s
    """, (order_id,))
    order = cur.fetchone()
    
    if not order:
        flash('Order not found.', 'danger')
        cur.close()
        return redirect(url_for('orders'))
    
    cur.execute("""
        SELECT p.product_name, oi.quantity, oi.price
        FROM Order_Items oi
        JOIN Products p ON oi.product_id = p.product_id
        WHERE oi.order_id = %s
    """, (order_id,))
    items = cur.fetchall()
    cur.close()
    return render_template('user/order_confirmation.html', order=order, items=items)

# User: Order history
@app.route('/orders')
def orders():
    if 'user_id' not in session:
        flash('Please log in to view your orders.', 'danger')
        return redirect(url_for('login'))
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT customer_id FROM Users WHERE user_id = %s", (session['user_id'],))
    customer = cur.fetchone()
    if not customer:
        flash('User not found.', 'danger')
        cur.close()
        return redirect(url_for('login'))
    
    cur.execute("""
        SELECT o.order_id, o.order_date, o.total_amount
        FROM Orders o
        WHERE o.customer_id = %s
        ORDER BY o.order_date DESC
    """, (customer['customer_id'],))
    orders = cur.fetchall()
    cur.close()
    return render_template('user/orders.html', orders=orders)

# Auth: Login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').encode('utf-8')
        
        if not re.match(USERNAME_REGEX, username):
            flash('Invalid username format.', 'danger')
            return render_template('auth/login.html')
        
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        try:
            cur.execute("SELECT user_id, password_hash, customer_id FROM Users WHERE username = %s", (username,))
            user = cur.fetchone()
            if user and user['password_hash'] and bcrypt.checkpw(password, user['password_hash'].encode('utf-8')):
                session['user_id'] = user['user_id']
                session['role'] = 'user'
                flash('Logged in successfully!', 'success')
                cur.close()
                return redirect(url_for('products'))
            
            cur.execute("SELECT account_id, password_hash, role FROM accounts WHERE username = %s", (username,))
            account = cur.fetchone()
            print(f"Account fetched: {account}")
            if account and account['password_hash']:
                print(f"Password hash: {account['password_hash']}")
                try:
                    if isinstance(account['password_hash'], str):
                        hash_bytes = account['password_hash'].encode('utf-8')
                    else:
                        hash_bytes = account['password_hash']
                    if bcrypt.checkpw(password, hash_bytes):
                        session['user_id'] = account['account_id']
                        session['role'] = account['role']
                        flash('Logged in successfully!', 'success')
                        cur.close()
                        return redirect(url_for('admin_dashboard'))
                    else:
                        print("Password validation failed.")
                except Exception as e:
                    print(f"bcrypt checkpw error: {str(e)}")
                    flash('Invalid credentials due to password validation error.', 'danger')
            
            flash('Invalid credentials.', 'danger')
            cur.close()
            return render_template('auth/login.html')
        
        except ValueError as e:
            print(f"bcrypt ValueError: {str(e)} - Username: {username}, User Hash: {user['password_hash'] if user else 'None'}, Account Hash: {account['password_hash'] if account else 'None'}")
            flash('An error occurred during login. Please contact support.', 'danger')
            cur.close()
            return render_template('auth/login.html')
        
        except Exception as e:
            print(f"Login error: {str(e)}")
            flash('An error occurred during login. Please try again.', 'danger')
            cur.close()
            return render_template('auth/login.html')
    
    return render_template('auth/login.html')

# Auth: Register
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').encode('utf-8')
        
        if not full_name or len(full_name) > 100:
            flash('Full name is required and must be 100 characters or less.', 'danger')
            return render_template('auth/register.html')
        if not re.match(EMAIL_REGEX, email):
            flash('Invalid email format.', 'danger')
            return render_template('auth/register.html')
        if not re.match(USERNAME_REGEX, username):
            flash('Username must be 3-50 characters, alphanumeric or underscore.', 'danger')
            return render_template('auth/register.html')
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('auth/register.html')
        
        cur = mysql.connection.cursor()
        cur.execute("SELECT user_id FROM Users WHERE username = %s", (username,))
        if cur.fetchone():
            flash('Username already exists.', 'danger')
            cur.close()
            return render_template('auth/register.html')
        
        password_hash = bcrypt.hashpw(password, bcrypt.gensalt()).decode('utf-8')
        try:
            cur.execute("""
                INSERT INTO Customers (full_name, email) VALUES (%s, %s)
            """, (full_name, email))
            customer_id = cur.lastrowid
            cur.execute("""
                INSERT INTO Users (customer_id, username, password_hash) VALUES (%s, %s, %s)
            """, (customer_id, username, password_hash))
            mysql.connection.commit()
            flash('Registration successful! Please log in.', 'success')
            cur.close()
            return redirect(url_for('login'))
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Registration failed: {str(e)}', 'danger')
            cur.close()
    return render_template('auth/register.html')

# Admin: Dashboard
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    cur = mysql.connection.cursor()
    cur.execute("SELECT COUNT(*) AS count FROM Products")
    product_count = cur.fetchone()['count']
    cur.execute("SELECT COUNT(*) AS count FROM Orders")
    order_count = cur.fetchone()['count']
    cur.close()
    return render_template('admin/dashboard.html', product_count=product_count, order_count=order_count)

# Admin: Product list

# def admin_required(f):
#     @wraps(f)
#     def decorated_function(*args, **kwargs):
#         if not current_user.is_authenticated or not current_user.is_admin:
#             flash('You do not have permission to access this page.', 'danger')
#             return redirect(url_for('login'))
#         return f(*args, **kwargs)
#     return decorated_function

@app.route('/admin/products')
@admin_required
def admin_products():
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM Products")
    products = cur.fetchall()
    cur.close()
    return render_template('admin/products/list.html', products=products)

@app.route('/admin/product/delete/<int:product_id>', methods=['POST'])
@admin_required
def admin_delete_product(product_id):
    try:
        cur = mysql.connection.cursor()
        cur.execute("DELETE FROM Products WHERE product_id = %s", (product_id,))
        mysql.connection.commit()
        cur.close()
        flash('Product deleted successfully.', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error deleting product: {str(e)}', 'danger')
    return redirect(url_for('admin_products'))
# Admin: Add/Edit product
@app.route('/admin/products/form', methods=['GET', 'POST'])
@admin_required
def admin_product_form():
    if request.method == 'POST':
        product_id = request.form.get('product_id')
        product_name = request.form.get('product_name', '').strip()
        brand = request.form.get('brand', '').strip()
        category = request.form.get('category', '').strip()
        try:
            price = float(request.form.get('price', 0))
            stock_quantity = int(request.form.get('stock_quantity', 0))
        except ValueError:
            flash('Price and stock quantity must be valid numbers.', 'danger')
            return render_template('admin/products/form.html', product=None)
        description = request.form.get('description', '').strip()
        
        # Handle image upload
        image_path = request.form.get('existing_image', '')
        file = request.files.get('image')
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            base, ext = os.path.splitext(filename)
            unique_filename = f"{base}_{secrets.token_hex(4)}{ext}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
            image_path = f"static/image/{unique_filename}"
        elif file and not allowed_file(file.filename):
            flash('Invalid image format. Allowed: png, jpg, jpeg, gif.', 'danger')
            return render_template('admin/products/form.html', product=None)
        
        # Validate inputs
        if not product_name or len(product_name) > 100:
            flash('Product name is required and must be 100 characters or less.', 'danger')
            return render_template('admin/products/form.html', product=None)
        if not brand or len(brand) > 50:
            flash('Brand is required and must be 50 characters or less.', 'danger')
            return render_template('admin/products/form.html', product=None)
        if not category or len(category) > 50:
            flash('Category is required and must be 50 characters or less.', 'danger')
            return render_template('admin/products/form.html', product=None)
        if price <= 0:
            flash('Price must be positive.', 'danger')
            return render_template('admin/products/form.html', product=None)
        if stock_quantity < 0:
            flash('Stock quantity cannot be negative.', 'danger')
            return render_template('admin/products/form.html', product=None)
        
        cur = mysql.connection.cursor()
        try:
            if product_id:
                cur.execute("""
                    UPDATE Products SET product_name = %s, brand = %s, category = %s, price = %s,
                    stock_quantity = %s, description = %s, image = %s WHERE product_id = %s
                """, (product_name, brand, category, price, stock_quantity, description, image_path, product_id))
            else:
                cur.execute("""
                    INSERT INTO Products (product_name, brand, category, price, stock_quantity, description, image)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (product_name, brand, category, price, stock_quantity, description, image_path))
            mysql.connection.commit()
            flash('Product saved successfully!', 'success')
            cur.close()
            return redirect(url_for('admin_products'))
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Failed to save product: {str(e)}', 'danger')
            cur.close()
    
    product_id = request.args.get('product_id')
    product = None
    if product_id:
        try:
            cur = mysql.connection.cursor()
            cur.execute("SELECT * FROM Products WHERE product_id = %s", (product_id,))
            product = cur.fetchone()
            cur.close()
            if not product:
                flash('Product not found.', 'danger')
                return redirect(url_for('admin_products'))
        except Exception:
            flash('Error retrieving product.', 'danger')
            cur.close()
            return redirect(url_for('admin_products'))
    return render_template('admin/products/form.html', product=product)

# Admin: Order list
@app.route('/admin/orders')
@admin_required
def admin_orders():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT o.order_id, o.order_date, o.total_amount, c.full_name
        FROM Orders o
        JOIN Customers c ON o.customer_id = c.customer_id
        ORDER BY o.order_date DESC
    """)
    orders = cur.fetchall()
    cur.close()
    return render_template('admin/orders/list.html', orders=orders)

# Admin: Order details
@app.route('/admin/orders/details/<int:order_id>')
@admin_required
def admin_order_details(order_id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT o.order_id, o.order_date, o.total_amount, c.full_name, s.full_name AS staff_name
        FROM Orders o
        JOIN Customers c ON o.customer_id = c.customer_id
        JOIN Staff s ON o.staff_id = s.staff_id
        WHERE o.order_id = %s
    """, (order_id,))
    order = cur.fetchone()
    
    if not order:
        flash('Order not found.', 'danger')
        cur.close()
        return redirect(url_for('admin_orders'))
    
    cur.execute("""
        SELECT p.product_name, oi.quantity, oi.price
        FROM Order_Items oi
        JOIN Products p ON oi.product_id = p.product_id
        WHERE oi.order_id = %s
    """, (order_id,))
    items = cur.fetchall()
    cur.close()
    return render_template('admin/orders/details.html', order=order, items=items)

# Logout
@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)

# if __name__ == '__main__':
    

    
    # port = int(os.environ.get('PORT', 5000))  # Use PORT env var or default to 5000
    # app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_ENV') == 'development')

    