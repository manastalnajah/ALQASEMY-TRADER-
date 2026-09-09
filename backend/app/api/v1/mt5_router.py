import asyncio
from database import SessionLocal
from app.indicators.moving_average import calculate_sma
from app.indicators.rsi import calculate_rsi
from app.logging.logger import system_logger
from sqlalchemy import text  

async def run_trading_cycle():
    db = SessionLocal()
    try:
        # 1. جلب الشموع الحقيقية اللحظية لإطار الدقيقة M1
        query = text("""
            SELECT close FROM candles 
            WHERE symbol_name = 'EURUSD' AND timeframe = 'M1'
            ORDER BY open_time DESC 
            LIMIT 50
        """)
        result = db.execute(query).fetchall()
        
        if len(result) < 20:
            return

        price_history = [row[0] for row in reversed(result)]
        current_price = price_history[-1]

        # 2. حساب المؤشرات الرياضية بدقة
        rsi_value = calculate_rsi(price_history, period=14)
        system_logger.info(f"📊 [Algorithmic Analysis] EURUSD Price: {current_price} | RSI: {rsi_value:.2f}")

        # 3. التحقق من عدم وجود أوامر معلقة حالياً لمنع التكدس
        check_pending = text("SELECT count(*) FROM trade_commands WHERE status = 'pending'")
        count_pending = db.execute(check_pending).scalar()

        if count_pending > 0:
            return # إذا كان هناك أمر جاري تنفيذه، ننتظر

        # 4. الاستراتيجية الخوارزمية الصارمة وإدارة رأس المال اللحظية
        signal = None
        
        # شروط سكالبينج صارمة: تشبع بيعي أو شرائي قوي
        if rsi_value < 30:
            signal = "BUY"
        elif rsi_value > 70:
            signal = "SELL"

        if signal:
            # 5. حساب المسافات الرياضية لوقف الخسارة وجني الأرباح (مثلاً 10 نقاط للسكالبينج السريع)
            # 0.00100 تعادل 10 نقاط (Pips) في أزواج الدولار
            pip_distance = 0.00100 
            
            if signal == "BUY":
                sl = current_price - pip_distance
                tp = current_price + pip_distance
            else: # SELL
                sl = current_price + pip_distance
                tp = current_price - pip_distance

            # إدخال الأمر بقواعد صارمة لا تقبل الخطأ
            insert_cmd = text("""
                INSERT INTO trade_commands 
                (symbol, order_type, lot_size, stop_loss, take_profit, status)
                VALUES 
                ('EURUSD', :order_type, 0.01, :sl, :tp, 'pending')
            """)
            
            db.execute(insert_cmd, {
                "order_type": signal,
                "sl": round(sl, 5),
                "tp": round(tp, 5)
            })
            db.commit()
            
            system_logger.info(f"🚀 [SIGNAL EXECUTED] {signal} Order Sent | SL: {sl:.5f} | TP: {tp:.5f}")

    except Exception as e:
        system_logger.error(f"❌ حدث خطأ خوارزمي أثناء الدورة: {str(e)}")
    finally:
        db.close() 

async def start_background_worker():
    system_logger.info("🚀 تشغيل محرك التداول الخوارزمي المستقل (إطار الدقيقة M1)...")
    while True:
        await run_trading_cycle()
        # فحص السوق كل ثانيتين لسرعة استجابة فائقة
        await asyncio.sleep(2)
