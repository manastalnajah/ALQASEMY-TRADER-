import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:candlesticks/candlesticks.dart'; // نموذج الشمعة الجاهز من المكتبة

class ChartService {
  static const String baseUrl = "https://YOUR_BACKEND_URL/api/v1/mt5";

  Future<List<Candle>> fetchCandles(String symbol, String timeframe) async {
    final response = await http.get(
      Uri.parse('$baseUrl/candles/data?symbol=$symbol&timeframe=$timeframe&limit=150'),
    );

    if (response.statusCode == 200) {
      final jsonResponse = jsonDecode(response.body);
      final List data = jsonResponse['data'];

      // تحويل البيانات القادمة من البايثون إلى كائن Candle الخاص بمكتبة فلاتر
      return data.map((json) {
        return Candle(
          date: DateTime.parse(json['date']),
          high: json['high'],
          low: json['low'],
          open: json['open'],
          close: json['close'],
          volume: json['volume'],
        );
      }).toList();
    } else {
      throw Exception('Failed to load candles');
    }
  }
}
