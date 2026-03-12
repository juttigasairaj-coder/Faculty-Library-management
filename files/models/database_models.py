from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class Admin(db.Model):
    """Admin user model"""
    __tablename__ = 'admin'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verify password"""
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<Admin {self.username}>'


class Author(db.Model):
    """Author model"""
    __tablename__ = 'author'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    bio = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship
    books = db.relationship('Book', backref='author', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Author {self.name}>'


class Faculty(db.Model):
    """Faculty model"""
    __tablename__ = 'faculty'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(15), nullable=False, unique=True)
    email = db.Column(db.String(120))
    department = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    transactions = db.relationship('TransactionHistory', backref='faculty', lazy=True)
    
    def __repr__(self):
        return f'<Faculty {self.name}>'


class Book(db.Model):
    """Book model"""
    __tablename__ = 'book'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('author.id'), nullable=False)
    isbn = db.Column(db.String(20), unique=True)
    info = db.Column(db.Text)
    publication_year = db.Column(db.Integer)
    status = db.Column(db.String(20), default='available')  # available, taken
    current_faculty_id = db.Column(db.Integer, db.ForeignKey('faculty.id'))
    issue_date = db.Column(db.DateTime)
    expected_return_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    current_faculty = db.relationship('Faculty', backref='books_taken')
    transactions = db.relationship('TransactionHistory', backref='book', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Book {self.title}>'
    
    def is_overdue(self):
        """Check if book is overdue"""
        if self.status == 'taken' and self.expected_return_date:
            return datetime.utcnow() > self.expected_return_date
        return False


class TransactionHistory(db.Model):
    """Transaction history model"""
    __tablename__ = 'transaction_history'
    
    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey('faculty.id'), nullable=False)
    issue_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expected_return_date = db.Column(db.DateTime, nullable=False)
    actual_return_date = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='taken')  # taken, returned, delayed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Transaction {self.id}>'
    
    def is_delayed(self):
        """Check if return is delayed"""
        if self.status == 'taken':
            return datetime.utcnow() > self.expected_return_date
        elif self.status == 'returned':
            return self.actual_return_date > self.expected_return_date
        return False