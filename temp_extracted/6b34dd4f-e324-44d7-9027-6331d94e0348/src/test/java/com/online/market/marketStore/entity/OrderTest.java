package com.online.market.marketStore.entity;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
public class OrderTest {

    @Mock
    private Long id;

    @InjectMocks
    private Order order;

    @BeforeEach
    void setup() {
        MockitoAnnotations.openMocks(this);
    }

    @Test
    public void testOrderConstructor_HappyPath_SetsFields() {
        // Act
        order = new Order();

        // Assert
        assertNotNull(order.getId());
        assertEquals(null, order.getProductName());
        assertEquals(null, order.getProductId());
        assertEquals(null, order.getPrice());
    }

    @Test
    public void testOrderConstructor_Id_SetCorrectly() {
        // Arrange
        Long expectedId = 1L;

        // Act
        order = new Order(expectedId);

        // Assert
        assertEquals(expectedId, order.getId());
        assertEquals(null, order.getProductName());
        assertEquals(null, order.getProductId());
        assertEquals(null, order.getPrice());
    }

    @Test
    public void testOrderConstructor_ProductName_SetCorrectly() {
        // Arrange
        String expectedProductName = "Product Name";

        // Act
        order = new Order(expectedProductName);

        // Assert
        assertNotNull(order.getId());
        assertEquals(expectedProductName, order.getProductName());
        assertEquals(null, order.getProductId());
        assertEquals(null, order.getPrice());
    }

    @Test
    public void testOrderConstructor_ProductId_SetCorrectly() {
        // Arrange
        Long expectedProductId = 1L;

        // Act
        order = new Order(expectedProductId);

        // Assert
        assertNotNull(order.getId());
        assertEquals(null, order.getProductName());
        assertEquals(expectedProductId, order.getProductId());
        assertEquals(null, order.getPrice());
    }

    @Test
    public void testOrderConstructor_Price_SetCorrectly() {
        // Arrange
        Integer expectedPrice = 10;

        // Act
        order = new Order(expectedPrice);

        // Assert
        assertNotNull(order.getId());
        assertEquals(null, order.getProductName());
        assertEquals(null, order.getProductId());
        assertEquals(expectedPrice, order.getPrice());
    }
}