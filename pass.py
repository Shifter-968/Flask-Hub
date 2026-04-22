from werkzeug.security import generate_password_hash

# Generate a hash for the password "Supersecret@1"
hashed_password = generate_password_hash("Supersecret@1")

print(hashed_password)

"""
INSERT INTO users (
    username,
    email,
    password,
    role
)
VALUES (
    'admin',
    'admin@example.com',
    'scrypt:32768:8:1$7Osxpr6kd42osx0N$2d1d58deebb49a758b0dbc0ee817bbcb6aff6cbde58769ce398b417033c3630d4bea062c609cd7b53c7c08e122f543714b33854024474e21e1b024fcdd0fe92e',
    'admin'
);
"""
