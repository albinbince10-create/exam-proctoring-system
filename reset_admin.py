import sqlite3

def reset_admin():
    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    # Check if an admin account already exists
    admin = cur.execute("SELECT email FROM users WHERE role='admin'").fetchone()

    if admin:
        # If an admin exists, update their email AND password
        cur.execute("UPDATE users SET email='albin@gmail.com', password='leo' WHERE role='admin'")
        print("Success! The admin account has been updated.")
        print("New Email: albin@gmail.com")
        print("New Password: leo")
    else:
        # If no admin exists at all, create a brand new one
        cur.execute("""
            INSERT INTO users (name, email, password, role) 
            VALUES ('Admin Albin', 'albin@gmail.com', 'leo', 'admin')
        """)
        print("Success! Created a new admin account.")
        print("Email: albin@gmail.com")
        print("Password: leo")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    reset_admin()