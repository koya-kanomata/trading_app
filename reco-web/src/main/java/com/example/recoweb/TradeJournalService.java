package com.example.recoweb;

import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVParser;
import org.apache.commons.csv.CSVPrinter;
import org.apache.commons.csv.CSVRecord;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.io.Reader;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;

@Service
public class TradeJournalService {
    private static final ZoneId JST = ZoneId.of("Asia/Tokyo");

    private final TradingProperties properties;

    public TradeJournalService(TradingProperties properties) {
        this.properties = properties;
    }

    public void recordTrade(TradeEntryForm form) throws IOException {
        String code = normalizeCode(form.getCode());
        String name = form.getName() == null ? "" : form.getName().trim();
        String side = form.getSide().trim().toUpperCase();
        int qty = form.getQty();
        double price = form.getPrice();
        LocalDate tradeDate = parseDateOrToday(form.getTradeDate());
        double pnl = form.getRealizedPnlJpy() == null ? 0.0 : form.getRealizedPnlJpy();

        if ("BUY".equals(side)) {
            pnl = 0.0;
        }

        appendFill(tradeDate, code, side, qty, price, pnl);
        updatePosition(tradeDate, code, name, side, qty, price);
    }

    private void appendFill(LocalDate tradeDate, String code, String side, int qty, double price, double pnl) throws IOException {
        Path fillsPath = Path.of(properties.getBaseDir(), properties.getFillsCsv());
        ensureCsv(fillsPath, List.of("fill_date", "code", "side", "qty", "price", "realized_pnl_jpy"));

        try (Writer writer = Files.newBufferedWriter(fillsPath, StandardCharsets.UTF_8, java.nio.file.StandardOpenOption.APPEND);
             CSVPrinter printer = new CSVPrinter(writer, CSVFormat.DEFAULT)) {
            printer.printRecord(
                    tradeDate,
                    code,
                    side,
                    qty,
                    String.format("%.4f", price),
                    String.format("%.4f", pnl)
            );
        }
    }

    private void updatePosition(LocalDate tradeDate, String code, String name, String side, int qty, double price) throws IOException {
        Path positionsPath = Path.of(properties.getBaseDir(), properties.getPositionsCsv());
        ensureCsv(positionsPath, List.of("code", "name", "qty", "entry_price", "entry_date", "status"));

        List<PositionRow> rows = loadPositions(positionsPath);

        PositionRow open = rows.stream()
                .filter(r -> code.equals(r.code) && "OPEN".equalsIgnoreCase(r.status))
                .findFirst()
                .orElse(null);

        if ("BUY".equals(side)) {
            if (open == null) {
                rows.add(new PositionRow(code, name, qty, price, tradeDate.toString(), "OPEN"));
            } else {
                int newQty = open.qty + qty;
                double weightedPrice = ((open.qty * open.entryPrice) + (qty * price)) / newQty;
                open.qty = newQty;
                open.entryPrice = weightedPrice;
                if (!name.isBlank()) {
                    open.name = name;
                }
            }
        } else {
            if (open == null) {
                throw new IllegalStateException("SELL入力: OPENポジションが見つかりません code=" + code);
            }
            if (qty > open.qty) {
                throw new IllegalStateException("SELL数量がOPEN数量を超えています code=" + code);
            }
            if (qty == open.qty) {
                open.status = "CLOSED";
            } else {
                open.qty = open.qty - qty;
            }
        }

        savePositions(positionsPath, rows);
    }

    private void ensureCsv(Path path, List<String> headers) throws IOException {
        if (Files.exists(path)) {
            return;
        }

        if (path.getParent() != null) {
            Files.createDirectories(path.getParent());
        }

        try (Writer writer = Files.newBufferedWriter(path, StandardCharsets.UTF_8);
             CSVPrinter printer = new CSVPrinter(writer, CSVFormat.DEFAULT)) {
            printer.printRecord(headers);
        }
    }

    private List<PositionRow> loadPositions(Path positionsPath) throws IOException {
        List<PositionRow> rows = new ArrayList<>();

        try (Reader reader = Files.newBufferedReader(positionsPath, StandardCharsets.UTF_8);
             CSVParser parser = CSVFormat.DEFAULT.builder().setHeader().setSkipHeaderRecord(true).build().parse(reader)) {
            for (CSVRecord record : parser) {
                rows.add(new PositionRow(
                        value(record, "code"),
                        value(record, "name"),
                        parseInt(value(record, "qty")),
                        parseDouble(value(record, "entry_price")),
                        value(record, "entry_date"),
                        value(record, "status")
                ));
            }
        }

        return rows;
    }

    private void savePositions(Path positionsPath, List<PositionRow> rows) throws IOException {
        try (Writer writer = Files.newBufferedWriter(positionsPath, StandardCharsets.UTF_8);
             CSVPrinter printer = new CSVPrinter(writer, CSVFormat.DEFAULT)) {
            printer.printRecord("code", "name", "qty", "entry_price", "entry_date", "status");
            for (PositionRow row : rows) {
                printer.printRecord(
                        row.code,
                        row.name,
                        row.qty,
                        String.format("%.4f", row.entryPrice),
                        row.entryDate,
                        row.status
                );
            }
        }
    }

    private String normalizeCode(String raw) {
        String digits = raw.replaceAll("\\D", "");
        if (digits.length() != 4) {
            throw new IllegalArgumentException("銘柄コードは4桁で入力してください");
        }
        return digits;
    }

    private LocalDate parseDateOrToday(String raw) {
        if (raw == null || raw.isBlank()) {
            return LocalDate.now(JST);
        }
        try {
            return LocalDate.parse(raw.trim());
        } catch (DateTimeParseException ex) {
            throw new IllegalArgumentException("取引日は YYYY-MM-DD 形式で入力してください");
        }
    }

    private int parseInt(String raw) {
        try {
            return Integer.parseInt(raw.trim());
        } catch (Exception ex) {
            return 0;
        }
    }

    private double parseDouble(String raw) {
        try {
            return Double.parseDouble(raw.trim());
        } catch (Exception ex) {
            return 0.0;
        }
    }

    private String value(CSVRecord record, String column) {
        if (!record.isMapped(column)) {
            return "";
        }
        return record.get(column);
    }

    private static class PositionRow {
        private final String code;
        private String name;
        private int qty;
        private double entryPrice;
        private final String entryDate;
        private String status;

        private PositionRow(String code, String name, int qty, double entryPrice, String entryDate, String status) {
            this.code = code;
            this.name = name == null ? "" : name;
            this.qty = qty;
            this.entryPrice = entryPrice;
            this.entryDate = entryDate == null ? "" : entryDate;
            this.status = (status == null || status.isBlank()) ? "OPEN" : status.toUpperCase();
        }
    }
}
