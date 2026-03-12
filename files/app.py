from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from functools import wraps
import os
from dotenv import load_dotenv

# Import models
from models.database_models import db, Admin, Author, Faculty, Book, TransactionHistory
from config import DevelopmentConfig

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(DevelopmentConfig)

# Initialize database
db.init_app(app)

# Helper function to send SMS (using Twilio)
def send_sms(phone, message):
    """Send SMS notification to faculty"""
    try:
        from twilio.rest import Client
        
        account_sid = app.config['TWILIO_ACCOUNT_SID']
        auth_token = app.config['TWILIO_AUTH_TOKEN']
        twilio_phone = app.config['TWILIO_PHONE_NUMBER']
        
        if account_sid == 'your_account_sid':  # Check if configured
            print(f"[SMS Mock] To: {phone}, Message: {message}")
            return True
        
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=message,
            from_=twilio_phone,
            to=phone
        )
        return True
    except Exception as e:
        print(f"SMS Error: {e}")
        return False

# Decorator for login required
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            flash('Please log in first', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==================== AUTHENTICATION ROUTES ====================

@app.route('/', methods=['GET', 'POST'])
def login():
    """Admin login page"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin = Admin.query.filter_by(username=username).first()
        
        if admin and admin.check_password(password):
            session['admin_id'] = admin.id
            session['username'] = admin.username
            flash(f'Welcome, {admin.username}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Admin logout"""
    session.clear()
    flash('You have been logged out', 'success')
    return redirect(url_for('login'))

# ==================== DASHBOARD ROUTES ====================

@app.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard"""
    total_books = Book.query.count()
    available_books = Book.query.filter_by(status='available').count()
    taken_books = Book.query.filter_by(status='taken').count()
    
    # Count delayed books
    delayed_books = TransactionHistory.query.filter(
        TransactionHistory.status == 'taken',
        TransactionHistory.expected_return_date < datetime.utcnow()
    ).count()
    
    total_faculty = Faculty.query.count()
    
    return render_template('dashboard.html',
                         total_books=total_books,
                         available_books=available_books,
                         taken_books=taken_books,
                         delayed_books=delayed_books,
                         total_faculty=total_faculty)

# ==================== BOOK ROUTES ====================

@app.route('/books')
@login_required
def books():
    """View all books with details"""
    page = request.args.get('page', 1, type=int)
    books_list = Book.query.paginate(page=page, per_page=10)
    return render_template('books.html', books=books_list)

@app.route('/books/search', methods=['GET', 'POST'])
@login_required
def search_books():
    """Search books by title or author"""
    results = []
    query = request.args.get('q', '')
    
    if query:
        results = Book.query.join(Author).filter(
            (Book.title.ilike(f'%{query}%')) |
            (Author.name.ilike(f'%{query}%'))
        ).all()
    
    return render_template('search_books.html', results=results, query=query)

@app.route('/books/allot', methods=['GET', 'POST'])
@login_required
def allot_book():
    """Allot a book to faculty"""
    if request.method == 'POST':
        book_id = request.form.get('book_id')
        faculty_name = request.form.get('faculty_name')
        faculty_phone = request.form.get('faculty_phone')
        
        # Get or create faculty
        faculty = Faculty.query.filter_by(phone=faculty_phone).first()
        if not faculty:
            faculty = Faculty(name=faculty_name, phone=faculty_phone)
            db.session.add(faculty)
            db.session.commit()
        
        # Get book
        book = Book.query.get(book_id)
        if not book or book.status != 'available':
            flash('Book is not available', 'error')
            return redirect(url_for('allot_book'))
        
        # Create transaction
        issue_date = datetime.utcnow()
        expected_return_date = issue_date + timedelta(days=app.config['BOOK_RETURN_DAYS'])
        
        book.status = 'taken'
        book.current_faculty_id = faculty.id
        book.issue_date = issue_date
        book.expected_return_date = expected_return_date
        
        transaction = TransactionHistory(
            book_id=book.id,
            faculty_id=faculty.id,
            expected_return_date=expected_return_date,
            status='taken'
        )
        
        db.session.add(transaction)
        db.session.commit()
        
        # Send SMS notification
        message = f"Hello {faculty_name}, you have been allotted '{book.title}'. Please return it by {expected_return_date.strftime('%d-%m-%Y')}"
        send_sms(faculty_phone, message)
        
        flash(f'Book "{book.title}" allotted to {faculty_name}', 'success')
        return redirect(url_for('books'))
    
    available_books = Book.query.filter_by(status='available').all()
    return render_template('allot_book.html', books=available_books)

@app.route('/books/return/<int:book_id>', methods=['GET', 'POST'])
@login_required
def return_book(book_id):
    """Return a book"""
    book = Book.query.get_or_404(book_id)
    
    if request.method == 'POST':
        actual_return_date = datetime.utcnow()
        
        # Get latest transaction
        transaction = TransactionHistory.query.filter_by(
            book_id=book_id,
            status='taken'
        ).order_by(TransactionHistory.id.desc()).first()
        
        if not transaction:
            flash('No active transaction found for this book', 'error')
            return redirect(url_for('books'))
        
        # Update transaction
        transaction.actual_return_date = actual_return_date
        
        if actual_return_date > transaction.expected_return_date:
            transaction.status = 'delayed'
            days_delayed = (actual_return_date - transaction.expected_return_date).days
            message = f"Book '{book.title}' returned {days_delayed} days late. Please try to return on time."
        else:
            transaction.status = 'returned'
            message = f"Thank you for returning '{book.title}' on time."
        
        # Update book status
        book.status = 'available'
        book.current_faculty_id = None
        book.issue_date = None
        book.expected_return_date = None
        
        db.session.commit()
        
        # Send SMS notification
        faculty = transaction.faculty
        send_sms(faculty.phone, message)
        
        flash(f'Book "{book.title}" returned successfully', 'success')
        return redirect(url_for('books'))
    
    return render_template('return_book.html', book=book)

# ==================== HISTORY ROUTES ====================

@app.route('/history')
@login_required
def history():
    """View transaction history"""
    page = request.args.get('page', 1, type=int)
    transactions = TransactionHistory.query.order_by(
        TransactionHistory.id.desc()
    ).paginate(page=page, per_page=10)
    return render_template('history.html', transactions=transactions)

@app.route('/delayed-books')
@login_required
def delayed_books():
    """View delayed books"""
    delayed = TransactionHistory.query.filter(
        TransactionHistory.status == 'taken',
        TransactionHistory.expected_return_date < datetime.utcnow()
    ).all()
    return render_template('delayed_books.html', delayed_books=delayed)

# ==================== FACULTY ROUTES ====================

@app.route('/faculty')
@login_required
def faculty_list():
    """View all faculty"""
    page = request.args.get('page', 1, type=int)
    faculty = Faculty.query.paginate(page=page, per_page=10)
    return render_template('faculty_management.html', faculty=faculty)

@app.route('/faculty/add', methods=['POST'])
@login_required
def add_faculty():
    """Add new faculty"""
    data = request.get_json()
    
    existing = Faculty.query.filter_by(phone=data['phone']).first()
    if existing:
        return jsonify({'error': 'Phone number already exists'}), 400
    
    faculty = Faculty(
        name=data['name'],
        phone=data['phone'],
        email=data.get('email'),
        department=data.get('department')
    )
    
    db.session.add(faculty)
    db.session.commit()
    
    return jsonify({'message': 'Faculty added successfully', 'id': faculty.id}), 201

@app.route('/faculty/delete/<int:faculty_id>', methods=['POST'])
@login_required
def delete_faculty(faculty_id):
    """Delete faculty"""
    faculty = Faculty.query.get_or_404(faculty_id)
    
    # Check if faculty has active books
    active_books = Book.query.filter_by(current_faculty_id=faculty_id, status='taken').first()
    if active_books:
        return jsonify({'error': 'Cannot delete faculty with active books'}), 400
    
    db.session.delete(faculty)
    db.session.commit()
    
    return jsonify({'message': 'Faculty deleted successfully'}), 200

# ==================== AUTHOR ROUTES ====================

@app.route('/authors')
@login_required
def author_list():
    """View all authors"""
    page = request.args.get('page', 1, type=int)
    authors = Author.query.paginate(page=page, per_page=10)
    return render_template('author_management.html', authors=authors)

@app.route('/authors/add', methods=['POST'])
@login_required
def add_author():
    """Add new author"""
    data = request.get_json()
    
    existing = Author.query.filter_by(name=data['name']).first()
    if existing:
        return jsonify({'error': 'Author already exists'}), 400
    
    author = Author(
        name=data['name'],
        bio=data.get('bio')
    )
    
    db.session.add(author)
    db.session.commit()
    
    return jsonify({'message': 'Author added successfully', 'id': author.id}), 201

# ==================== BOOK MANAGEMENT ROUTES ====================

@app.route('/book-management')
@login_required
def book_management():
    """Manage books (CRUD)"""
    page = request.args.get('page', 1, type=int)
    books_list = Book.query.paginate(page=page, per_page=10)
    authors = Author.query.all()
    return render_template('book_management.html', books=books_list, authors=authors)

@app.route('/book/add', methods=['POST'])
@login_required
def add_book():
    """Add new book"""
    data = request.get_json()
    
    existing = Book.query.filter_by(isbn=data['isbn']).first()
    if existing:
        return jsonify({'error': 'ISBN already exists'}), 400
    
    book = Book(
        title=data['title'],
        author_id=data['author_id'],
        isbn=data.get('isbn'),
        info=data.get('info'),
        publication_year=data.get('publication_year'),
        status='available'
    )
    
    db.session.add(book)
    db.session.commit()
    
    return jsonify({'message': 'Book added successfully', 'id': book.id}), 201

@app.route('/book/delete/<int:book_id>', methods=['POST'])
@login_required
def delete_book(book_id):
    """Delete book"""
    book = Book.query.get_or_404(book_id)
    
    if book.status == 'taken':
        return jsonify({'error': 'Cannot delete book that is currently taken'}), 400
    
    db.session.delete(book)
    db.session.commit()
    
    return jsonify({'message': 'Book deleted successfully'}), 200

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(error):
    """Handle 500 errors"""
    return render_template('500.html'), 500

# ==================== CONTEXT PROCESSORS ====================

@app.context_processor
def inject_user():
    """Inject user into template context"""
    return {
        'username': session.get('username'),
        'logged_in': 'admin_id' in session
    }

# ==================== DATABASE INITIALIZATION ====================

def init_db():
    """Initialize database with sample data"""
    with app.app_context():
        db.create_all()
        
        # Check if admin exists
        admin = Admin.query.filter_by(username='admin').first()
        if not admin:
            admin = Admin(username='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("✓ Admin user created (username: admin, password: admin123)")
        
        # Add sample authors if none exist
        if Author.query.count() == 0:
            authors = [
                Author(name='J.K. Rowling', bio='British author of Harry Potter series'),
                Author(name='George R.R. Martin', bio='American novelist and writer'),
                Author(name='J.R.R. Tolkien', bio='English writer and philologist'),
                Author(name='Stephen King', bio='American author of horror and supernatural fiction'),
            ]
            db.session.add_all(authors)
            db.session.commit()
            print("✓ Sample authors created")
        
        # Add sample books if none exist
        if Book.query.count() == 0:
            books = [
                Book(title='Harry Potter and the Philosopher\'s Stone', author_id=1, isbn='9780747532699', info='The first book in the Harry Potter series'),
                Book(title='A Game of Thrones', author_id=2, isbn='9780553103540', info='The first novel in A Song of Ice and Fire'),
                Book(title='The Hobbit', author_id=3, isbn='9780547928227', info='Fantasy adventure novel'),
                Book(title='The Shining', author_id=4, isbn='9780385333312', info='Psychological horror novel'),
            ]
            db.session.add_all(books)
            db.session.commit()
            print("✓ Sample books created")

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)