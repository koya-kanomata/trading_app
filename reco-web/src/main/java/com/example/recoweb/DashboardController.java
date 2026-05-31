package com.example.recoweb;

import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.validation.BindingResult;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ModelAttribute;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

import jakarta.validation.Valid;

import java.io.IOException;
import java.time.ZoneId;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;

@Controller
public class DashboardController {
    private static final DateTimeFormatter TS_FORMAT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss z")
            .withZone(ZoneId.of("Asia/Tokyo"));

    private final RecommendationService recommendationService;
    private final TradingRunnerService runnerService;
    private final TradeJournalService tradeJournalService;

    public DashboardController(
            RecommendationService recommendationService,
            TradingRunnerService runnerService,
            TradeJournalService tradeJournalService
    ) {
        this.recommendationService = recommendationService;
        this.runnerService = runnerService;
        this.tradeJournalService = tradeJournalService;
    }

    @GetMapping("/")
    public String index(Model model) {
        loadDashboard(model);
        return "index";
    }

    @GetMapping("/trades/new")
    public String newTrade(Model model) {
        if (!model.containsAttribute("tradeForm")) {
            TradeEntryForm tradeForm = new TradeEntryForm();
            tradeForm.setTradeDate(LocalDate.now(ZoneId.of("Asia/Tokyo")).toString());
            tradeForm.setSide("BUY");
            model.addAttribute("tradeForm", tradeForm);
        }
        return "trade-entry";
    }

    @PostMapping("/trades")
    public String submitTrade(
            @Valid @ModelAttribute("tradeForm") TradeEntryForm tradeForm,
            BindingResult bindingResult,
            Model model,
            RedirectAttributes redirectAttributes
    ) {
        if (bindingResult.hasErrors()) {
            return "trade-entry";
        }

        try {
            tradeJournalService.recordTrade(tradeForm);
            redirectAttributes.addFlashAttribute("message", "約定を記録しました");
        } catch (Exception ex) {
            model.addAttribute("error", "約定記録に失敗しました: " + ex.getMessage());
            return "trade-entry";
        }
        return "redirect:/trades/new";
    }

    @PostMapping("/run-now")
    public String runNow(RedirectAttributes redirectAttributes) {
        TradingRunnerService.RunResult result = runnerService.runNow("manual-web");
        if (result.success()) {
            redirectAttributes.addFlashAttribute("message", "手動実行が完了しました");
        } else {
            redirectAttributes.addFlashAttribute("error",
                    "手動実行に失敗しました (exit=" + result.exitCode() + ") " + result.output());
        }
        return "redirect:/";
    }

    private void loadDashboard(Model model) {
        try {
            RecommendationSnapshot snapshot = recommendationService.loadSnapshot();
            model.addAttribute("buyRows", snapshot.buyRows());
            model.addAttribute("sellRows", snapshot.sellRows());
            model.addAttribute("lastUpdated", snapshot.lastUpdated() == null ? "-" : TS_FORMAT.format(snapshot.lastUpdated()));
        } catch (IOException ex) {
            model.addAttribute("loadError", ex.getMessage());
            model.addAttribute("buyRows", java.util.List.of());
            model.addAttribute("sellRows", java.util.List.of());
            model.addAttribute("lastUpdated", "-");
        }
    }
}
