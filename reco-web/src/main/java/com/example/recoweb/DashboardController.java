package com.example.recoweb;

import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

import java.io.IOException;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

@Controller
public class DashboardController {
    private static final DateTimeFormatter TS_FORMAT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss z")
            .withZone(ZoneId.of("Asia/Tokyo"));

    private final RecommendationService recommendationService;
    private final TradingRunnerService runnerService;

    public DashboardController(RecommendationService recommendationService, TradingRunnerService runnerService) {
        this.recommendationService = recommendationService;
        this.runnerService = runnerService;
    }

    @GetMapping("/")
    public String index(Model model) {
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
        return "index";
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
}
