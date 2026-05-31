package com.example.recoweb;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;

public class TradeEntryForm {
    @NotBlank(message = "銘柄コードは必須です")
    @Pattern(regexp = "\\d{4}", message = "銘柄コードは4桁の数字で入力してください")
    private String code;

    private String name;

    @NotBlank(message = "売買区分は必須です")
    @Pattern(regexp = "BUY|SELL", message = "売買区分は BUY または SELL です")
    private String side;

    @Min(value = 1, message = "株数は1以上で入力してください")
    private int qty;

    @DecimalMin(value = "0.01", message = "約定価格は0より大きい値を入力してください")
    private double price;

    private String tradeDate;

    private Double realizedPnlJpy;

    public String getCode() {
        return code;
    }

    public void setCode(String code) {
        this.code = code;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getSide() {
        return side;
    }

    public void setSide(String side) {
        this.side = side;
    }

    public int getQty() {
        return qty;
    }

    public void setQty(int qty) {
        this.qty = qty;
    }

    public double getPrice() {
        return price;
    }

    public void setPrice(double price) {
        this.price = price;
    }

    public String getTradeDate() {
        return tradeDate;
    }

    public void setTradeDate(String tradeDate) {
        this.tradeDate = tradeDate;
    }

    public Double getRealizedPnlJpy() {
        return realizedPnlJpy;
    }

    public void setRealizedPnlJpy(Double realizedPnlJpy) {
        this.realizedPnlJpy = realizedPnlJpy;
    }
}
