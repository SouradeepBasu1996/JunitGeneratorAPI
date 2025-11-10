package com.online.market.marketStore;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Mockito;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
public class MarketStoreApplicationTest {

    @Mock
    private SpringApplication springApplication;

    @InjectMocks
    private MarketStoreApplication marketStoreApplication;

    @BeforeEach
    void setUp() {
        Mockito.reset(springApplication);
    }

    @Test
    public void testMainMethod_HappyPath() {
        // Arrange
        when(springApplication.run(MarketStoreApplication.class, new String[0])).thenReturn(null);

        // Act
        marketStoreApplication.main(new String[0]);

        // Assert
        verify(springApplication).run(MarketStoreApplication.class, new String[0]);
    }

    @Test
    public void testMainMethod_NullArguments() {
        // Arrange
        when(springApplication.run(MarketStoreApplication.class, null)).thenThrow(new NullPointerException());

        // Act
        try {
            marketStoreApplication.main(null);
        } catch (NullPointerException e) {
            assertEquals("null", e.getMessage());
        }

        // Assert
        verify(springApplication).run(MarketStoreApplication.class, null);
    }
}