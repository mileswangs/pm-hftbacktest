class PolymarketIntegrationError(RuntimeError):
    pass


class PolymarketDependencyError(PolymarketIntegrationError):
    pass


class PolymarketConfigurationError(PolymarketIntegrationError):
    pass
