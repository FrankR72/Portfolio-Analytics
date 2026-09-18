

from sqlalchemy.ext.asyncio import AsyncSession




class HoldingService:
    def __init__(self, session: AsyncSession):
        self.db = session
        
        
    