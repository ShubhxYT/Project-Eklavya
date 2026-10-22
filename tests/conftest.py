"""Never load developer dotenv files during test collection."""
import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False
