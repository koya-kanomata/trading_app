package com.example.recoweb;

public record RecommendationRow(
        String tradeDate,
        String code,
        String name,
        String side,
        String qty,
        String entryLimit,
        String stopLoss,
        String takeProfit,
        String memo
) {
}
