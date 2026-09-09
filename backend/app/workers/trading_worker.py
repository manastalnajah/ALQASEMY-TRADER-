import asyncio
import random
from database import SessionLocal
from app.indicators.moving_average import calculate_sma
from app.indicators.rsi import calculate_rsi
from app.services.strategy_service import evaluate_and_execute_strategy
from app.logging.logger import system_logger
from sqlalchemy import text  

async def run_trading_cycle():
    db = SessionLocal()
    try:
        # 🔴 التعديل هنا: أعدناها إلى M5 لأن الروبوت يرسل M5 وليس M1
        query = text("""
            SELECT close FROM candles 
            WHERE symbol_name = 'EURUSD' AND timeframe = 'M5'
            ORDER BY open_time DESC 
            LIMIT 50
        """)
        result = db.execute(query).fetchall()
        
        if len(result) < 20:
            system_logger.info("⏳ بانتظار تجميع شمعات كافية من ميتاتريدر لحساب المؤشرات...")
            return

        price_history = [row[0] for row in reversed(result)]
        current_price = price_history[-1]

        fast_ma = calculate_sma(price_history, period=10)
        slow_ma = calculate_sma(price_history, period=50)
        rsi_value = calculate_rsi(price_history, period=14)

        market_data = {
            "symbol": "EURUSD",
            "price": current_price,
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "rsi": rsi_value
        }

        system_logger.info(f"📊 [Live Strategy Analysis] EURUSD Price: {current_price} | RSI: {rsi_value}")

        # =========================================================
        # 🚀 إضافة مؤقتة لإجبار النظام على فتح صفقة واختبار MT5 🚀
        # =========================================================
        check_pending = text("SELECT count(*) FROM trade_commands WHERE status = 'pending'")
        count_pending = db.execute(check_pending).scalar()

        if count_pending == 0:
            system_logger.info("🚨 جاري إرسال صفقة شراء إجبارية لاختبار التنفيذ في الميتاتريدر...")
            test_query = text("""
                INSERT INTO trade_commands (symbol, order_type, lot_size, stop_loss, take_profit, status)
                VALUES ('EURUSD', 'BUY', 0.01, 0, 0, 'pending')
            """)
            db.execute(test_query)
            db.commit()
            system_logger.info("✅ تم وضع أمر الشراء التجريبي بنجاح! راقب الميتاتريدر الآن.")
        # =========================================================

        evaluate_and_execute_strategy(
            db=db, 
            strategy_name="rsi", 
            market_data=market_data
        )
        
    except Exception as e:
        system_logger.error(f"❌ حدث خطأ أثناء تنفيذ الدورة: {str(e)}")
    finally:
        db.close() 

async def start_background_worker():
    system_logger.info("🚀 تشغيل محرك التداول الآلي في الخلفية (إطار M5)...")
    while True:
        await run_trading_cycle()
        await asyncio.sleep(2)
