from sqlalchemy import Column, Integer, String
from database import Base

class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String)
    app_password = Column(String)
    domain = Column(String)
    resume = Column(String)
    status = Column(String)


class HR(Base):
    __tablename__ = "hrs"

    id = Column(Integer, primary_key=True, index=True)
    company = Column(String)
    hr_name = Column(String)
    email = Column(String)
    domain = Column(String)


class Outreach(Base):
    __tablename__ = "outreach"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer)
    hr_id = Column(Integer)
    stage = Column(String)
    last_sent = Column(String)
