from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    # admin, teacher, student, parent
    role = db.Column(db.String(20), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


"""
class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    school_type = db.Column(db.String(50), nullable=False)
    location = db.Column(db.Text, nullable=False)

    classrooms = db.relationship("Classroom", backref="school", lazy=True)
    students = db.relationship("Student", backref="school", lazy=True)
    teachers = db.relationship("Teacher", backref="school", lazy=True)
    parents = db.relationship("Parent", backref="school", lazy=True)
"""


class School(db.Model):
    __tablename__ = "schools"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    # pre_school, primary_school, high_school, tertiary
    school_type = db.Column(db.String(50), nullable=False)
    location = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(20), nullable=True)
    logo = db.Column(db.String(255), nullable=True)  # path to logo file

    SCHOOL_TYPE_CHOICES = {
        "pre_school": "Pre-School",
        "primary_school": "Primary School",
        "high_school": "High School",
        "tertiary": "Tertiary Institution",
    }

    def get_school_type_display(self):
        return self.SCHOOL_TYPE_CHOICES.get(self.school_type, self.school_type)

    def __repr__(self):
        return f"<School {self.name} ({self.get_school_type_display()})>"


class Classroom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey(
        "school.id"), nullable=False)
    students = db.relationship("Student", backref="classroom", lazy=True)


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey(
        "school.id"), nullable=False)
    classroom_id = db.Column(
        db.Integer, db.ForeignKey("classroom.id"), nullable=True)
    submissions = db.relationship("Submission", backref="student", lazy=True)
    results = db.relationship("TermResult", backref="student", lazy=True)


class Teacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey(
        "school.id"), nullable=False)


class Parent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey(
        "school.id"), nullable=False)


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    date = db.Column(db.DateTime, nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey(
        "school.id"), nullable=False)


class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=True)
    submitted_at = db.Column(db.DateTime, default=db.func.now())
    student_id = db.Column(db.Integer, db.ForeignKey(
        "student.id"), nullable=False)


class TermResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(100), nullable=False)
    grade = db.Column(db.String(10), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey(
        "student.id"), nullable=False)
