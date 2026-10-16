import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

def send_otp_email(to_email: str, otp_code: str):
    smtp_email = os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if not smtp_email or not smtp_password:
        print("❌ Error: Missing Gmail SMTP credentials in .env")
        return False

    msg = MIMEMultipart()
    msg['From'] = f"Kurukshetra Support <{smtp_email}>"
    msg['To'] = to_email
    msg['Subject'] = "Kurukshetra: Password Reset OTP"

    html_content = f'''
        <div style="font-family: Arial, sans-serif; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px; max-width: 500px; margin: 0 auto;">
            <h2 style="color: #1e293b;">Password Reset Verification</h2>
            <p style="color: #64748b;">Use the verification code below to reset your password. This code expires in 10 minutes.</p>
            <div style="background-color: #f1f5f9; padding: 15px; border-radius: 6px; text-align: center; margin: 20px 0;">
                <span style="font-size: 32px; font-weight: bold; letter-spacing: 6px; color: #2563eb;">{otp_code}</span>
            </div>
            <p style="color: #94a3b8; font-size: 12px;">If you did not request this code, please ignore this email.</p>
        </div>
    '''
    msg.attach(MIMEText(html_content, 'html'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
        print(f"✅ Email sent via Gmail SMTP to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Gmail SMTP Error: {str(e)}")
        return False