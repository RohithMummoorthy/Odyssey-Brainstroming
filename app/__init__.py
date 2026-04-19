"""Flask application factory."""
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template
from flask_cors import CORS

from .config import Config

# Resolve the frontend directory (lives alongside the project root)
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def create_app(config_object: type = Config) -> Flask:
    """Create and configure the Flask application.

    Args:
        config_object: Configuration class to use (defaults to Config).

    Returns:
        Configured Flask application instance.
    """
    app = Flask(
        __name__,
        template_folder=str(_FRONTEND_DIR / "templates"),
        static_folder=str(_FRONTEND_DIR / "static"),
        static_url_path="/static",
    )
    app.config.from_object(config_object)

    # ------------------------------------------------------------------ #
    # CORS — allow all origins so Render + local dev work out of the box  #
    # ------------------------------------------------------------------ #
    CORS(app, origins="*", supports_credentials=True)

    # ------------------------------------------------------------------ #
    # Middleware (IP allow-list with 60 s cache)                          #
    # ------------------------------------------------------------------ #
    from .middleware import init_middleware
    init_middleware(app)

    # ------------------------------------------------------------------ #
    # Blueprints                                                           #
    # ------------------------------------------------------------------ #
    from .routes.auth        import auth_bp
    from .routes.quiz        import quiz_bp
    from .routes.audit       import audit_bp
    from .routes.admin       import admin_bp
    from .routes.leaderboard import leaderboard_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(quiz_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(leaderboard_bp)

    # ------------------------------------------------------------------ #
    # HTML page routes                                                     #
    # ------------------------------------------------------------------ #
    @app.route("/")
    @app.route("/login")
    def login_page():
        """Serve the team login page."""
        return render_template("login.html")

    @app.route("/admin-panel")
    def admin_panel():
        """Serve the admin dashboard."""
        return render_template("admin.html")

    # ------------------------------------------------------------------ #
    # Health-check route (Render liveness probe + pre_event_check.py)    #
    # ------------------------------------------------------------------ #
    @app.route("/health")
    def health():
        return jsonify(
            {
                "message": "hi",
                "status":    "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ), 200

    # ------------------------------------------------------------------ #
    # Background scheduler — auto-submit expired sessions                 #
    # Skip in testing to avoid scheduler threads polluting test runs.     #
    # ------------------------------------------------------------------ #
    if not app.config.get("TESTING"):
        from .services.timer_service import init_scheduler
        init_scheduler(app)

    return app
