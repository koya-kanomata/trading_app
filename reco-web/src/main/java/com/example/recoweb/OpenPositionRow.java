package com.example.recoweb;

public record OpenPositionRow(
        String code,
        String name,
        int qty,
        String entryPrice,
        String entryDate,
        String status
) {
}