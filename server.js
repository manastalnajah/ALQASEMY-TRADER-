require('dotenv').config();
const { WebSocketServer } = require('ws');
const { createClient } = require('@supabase/supabase-js');

// 1. تهيئة الاتصال بقاعدة بيانات Supabase
const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!supabaseUrl || !supabaseKey) {
    console.error('❌ Missing Supabase URL or Key in environment variables!');
    process.exit(1);
}

const supabase = createClient(supabaseUrl, supabaseKey);

// 2. إنشاء خادم WebSocket على المنفذ المخصص (Render سيقوم بتحديد المنفذ تلقائياً)
const port = process.env.PORT || 8000;
const wss = new WebSocketServer({ port: port });

let mt5Client = null;

console.log(`🚀 Bridge Server is starting on port ${port}...`);

// 3. الاستماع لاتصالات MT5
wss.on('connection', (ws) => {
    console.log('✅ MetaTrader 5 Connected successfully!');
    mt5Client = ws;

    // عندما يرسل MT5 رسالة
    ws.on('message', async (message) => {
        try {
            const data = JSON.parse(message);
            console.log('📩 Received from MT5:', data);

            // حفظ الأحداث في جدول bot_events
            if (data.action === 'log_event') {
                const { error } = await supabase
                    .from('bot_events')
                    .insert([{
                        account_id: data.accountId,
                        event_type: data.eventType,
                        severity: data.severity,
                        message: data.message,
                        details: data.details
                    }]);
                
                if (error) console.error('❌ Error saving event to DB:', error.message);
            }
        } catch (err) {
            console.error('❌ Error parsing message from MT5:', err.message);
        }
    });

    ws.on('close', () => {
        console.log('⚠️ MetaTrader 5 Disconnected!');
        mt5Client = null;
    });
});

// 4. مراقبة قاعدة البيانات وإرسال الأوامر إلى MT5
supabase
    .channel('custom-all-channel')
    .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'commands' },
        (payload) => {
            console.log('🔥 New command received from Flutter App:', payload.new);
            
            if (mt5Client && mt5Client.readyState === 1) { // 1 means OPEN
                mt5Client.send(JSON.stringify(payload.new));
                console.log('📤 Command sent to MT5');
            } else {
                console.log('⚠️ Cannot send command, MT5 is not connected.');
            }
        }
    )
    .subscribe();

console.log('👂 Listening for database changes and MT5 connections...');
