from passlib.context import CryptContext # type: ignore

pwd_cxt = CryptContext(schemes=["bcrypt"], deprecated = "auto")

class Hash():
    @staticmethod
    def bcrypt(password : str):
        return pwd_cxt.hash(password)
    @staticmethod
    def verify (plain_pass: str, hashed_pass: str):
        return pwd_cxt.verify(plain_pass, hashed_pass)
