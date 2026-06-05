from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Date, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

engine = create_engine('sqlite:///d.db')
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

class Booking(Base):
    __tablename__ = 'bookings'
    id = Column(Integer, primary_key=True)
    home_id = Column(Integer)
    check_in = Column(Date)
    check_out = Column(Date)
    name = Column(String)
    phone = Column(String)
    email = Column(String)
    early_checkin = Column(Boolean, default=False)
    late_checkout = Column(Boolean, default=False)
    parking = Column(Boolean, default=False)
    total_price = Column(Integer)
    status = Column(String, default='new')
    created_at = Column(DateTime, default=datetime.utcnow)
    peoples = Column(String)

Base.metadata.create_all(bind=engine)