package com.example.recoweb;

import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVParser;
import org.apache.commons.csv.CSVRecord;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

@Service
public class RecommendationService {
    private final TradingProperties properties;

    public RecommendationService(TradingProperties properties) {
        this.properties = properties;
    }

    public RecommendationSnapshot loadSnapshot() throws IOException {
        Path csvPath = Path.of(properties.getBaseDir(), properties.getOrdersCsv());
        if (!Files.exists(csvPath)) {
            return new RecommendationSnapshot(null, List.of(), List.of());
        }

        List<RecommendationRow> buyRows = new ArrayList<>();
        List<RecommendationRow> sellRows = new ArrayList<>();

        try (Reader reader = Files.newBufferedReader(csvPath, StandardCharsets.UTF_8);
             CSVParser parser = CSVFormat.DEFAULT.builder().setHeader().setSkipHeaderRecord(true).build().parse(reader)) {

            for (CSVRecord record : parser) {
                RecommendationRow row = new RecommendationRow(
                        value(record, "trade_date"),
                        value(record, "code"),
                        value(record, "name"),
                        value(record, "side"),
                        value(record, "qty"),
                        value(record, "entry_limit"),
                        value(record, "stop_loss"),
                        value(record, "take_profit"),
                        value(record, "memo")
                );

                String side = row.side() == null ? "" : row.side().trim().toUpperCase();
                if ("SELL".equals(side)) {
                    sellRows.add(row);
                } else {
                    buyRows.add(row);
                }
            }
        }

        Instant updated = Files.getLastModifiedTime(csvPath).toInstant();
        return new RecommendationSnapshot(updated, buyRows, sellRows);
    }

    private String value(CSVRecord record, String column) {
        if (!record.isMapped(column)) {
            return "";
        }
        return record.get(column);
    }
}
