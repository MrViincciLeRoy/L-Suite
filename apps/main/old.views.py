from django.shortcuts import render

# Create your views here.
# ============================================================================
# lsuite/main/routes.py - CORRECTED VERSION
# ============================================================================
"""
Main Blueprint - Dashboard and Home
"""
#from flask import render_template, jsonify
from django.contrib.auth.decorators import login_required
from .models import EmailStatement, BankTransaction, TransactionCategory,ERPNextConfig, ERPNextSyncLog
from sqlalchemy import func
from datetime import datetime
#from lsuite.main import main_bp


#@main_bp.route('/')
#@login_required
def index(request):
    """Dashboard home page"""
    
    try:
        # Get statistics - with safe defaults
        stats = {
            'statements': EmailStatement.query.count(),
            'transactions': BankTransaction.query.count(),
            'categorized': BankTransaction.query.filter(
                BankTransaction.category_id.isnot(None)
            ).count(),
            'synced': BankTransaction.query.filter_by(erpnext_synced=True).count(),
        }
    except Exception:
        stats = {
            'statements': 0,
            'transactions': 0,
            'categorized': 0,
            'synced': 0
        }
    
    try:
        # Recent statements
        recent_statements = EmailStatement.query.order_by(
            EmailStatement.received_date.desc()
        ).limit(5).all()
    except Exception:
        recent_statements = []
    
    try:
        # Recent transactions
        recent_transactions = BankTransaction.query.order_by(
            BankTransaction.date.desc()
        ).limit(10).all()
    except Exception:
        recent_transactions = []
    
    try:
        # Category breakdown
        from lsuite.extensions import db
        category_stats = db.session.query(
            TransactionCategory.name,
            func.count(BankTransaction.id).label('count')
        ).outerjoin(
            BankTransaction, BankTransaction.category_id == TransactionCategory.id
        ).group_by(
            TransactionCategory.name
        ).all()
    except Exception:
        category_stats = []
    
    try:
        # Recent sync logs
        recent_syncs = ERPNextSyncLog.query.order_by(
            ERPNextSyncLog.sync_date.desc()
        ).limit(5).all()
    except Exception:
        recent_syncs = []
    
    try:
        # ERPNext config status
        erpnext_config = ERPNextConfig.query.filter_by(is_active=True).first()
    except Exception:
        erpnext_config = None
    
    try:
        # Calculate ready to sync
        ready_to_sync = BankTransaction.query.filter(
            BankTransaction.category_id.isnot(None),
            BankTransaction.erpnext_synced == False
        ).count()
    except Exception:
        ready_to_sync = 0
    
    return render(request,
        'main/index.html',
        {'stats':stats,
        'recent_statements':recent_statements,
        'recent_transactions':recent_transactions,
        'category_stats':category_stats,
        'recent_syncs':recent_syncs,
        'erpnext_config':erpnext_config,
        'ready_to_sync':ready_to_sync}
    )


#@main_bp.route('/health')
def health_check(request):
    """Health check endpoint for monitoring (no authentication required)"""
    try:
        from lsuite.extensions import db
        # Test database connection
        db.session.execute(db.text('SELECT 1'))
        db_status = 'healthy'
    except Exception as e:
        db_status = f'unhealthy: {str(e)}'
    
    return jsonify({
        'status': 'ok',
        'app': 'LSuite',
        'version': '1.0.0',
        'database': db_status,
        'timestamp': datetime.utcnow().isoformat()
    }), 200


#@main_bp.route('/about')
def about(request):
    """About page"""
    return render(request,'main/about.html')