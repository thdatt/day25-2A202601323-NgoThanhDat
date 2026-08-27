from quanlity_guardrail import ProductionAgentGateway


def test_degraded_http_200_is_blocked():
    gateway = ProductionAgentGateway(quality_slo_threshold=0.75)
    result = gateway.handle_request(
        "Thời hạn hoàn tiền là bao lâu?",
        "Quy định: thời hạn hoàn tiền tối đa là 30 ngày.",
    )
    assert result["status"] == "degraded_quality_detected"
    assert result["metrics"]["http_status"] == 200
    assert result["metrics"]["is_slo_violated"] is True


def test_good_quality_passes():
    gateway = ProductionAgentGateway(quality_slo_threshold=0.75)
    result = gateway.evaluate(
        "Hoàn tiền tối đa 30 ngày.",
        "Hoàn tiền tối đa 30 ngày.",
        "Hoàn tiền bao lâu?",
        faithfulness_fn=lambda *_: 0.95,
        relevancy_fn=lambda *_: 0.90,
    )
    assert result["status"] == "success"
