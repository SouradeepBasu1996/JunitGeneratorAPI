package com.online.shop.ShopOnline.entity;

import com.online.shop.ShopOnline.entity.Order;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.util.*;
import java.util.ArrayList;
import java.util.Optional;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

public class OrderTest {

    @Test
    void testNoArgsConstructor() {
        Order order = new Order();
        assertNotNull(order);
        assertNull(order.getId());
        assertNull(order.getProductName());
        assertNull(order.getProductId());
        assertNull(order.getPrice());
    }

    @Test
    void testAllArgsConstructor() {
        Long id = 1L;
        String productName = "Product Name";
        Long productId = 2L;
        Integer price = 10;

        Order order = new Order(id, productName, productId, price);
        assertEquals(id, order.getId());
        assertEquals(productName, order.getProductName());
        assertEquals(productId, order.getProductId());
        assertEquals(price, order.getPrice());
    }

    @Test
    void testGetterSetter() {
        Long id = 1L;
        String productName = "Product Name";
        Long productId = 2L;
        Integer price = 10;

        Order order = new Order(id, productName, productId, price);
        assertEquals(id, order.getId());
        assertEquals(productName, order.getProductName());
        assertEquals(productId, order.getProductId());
        assertEquals(price, order.getPrice());

        order.setId(3L);
        order.setProductName("New Product Name");
        order.setProductId(4L);
        order.setPrice(20);

        assertEquals(3L, order.getId());
        assertEquals("New Product Name", order.getProductName());
        assertEquals(4L, order.getProductId());
        assertEquals(20, order.getPrice());
    }

    @Test
    void testBuilder() {
        Long id = 1L;
        String productName = "Product Name";
        Long productId = 2L;
        Integer price = 10;

        Order order = Order.builder()
                .id(id)
                .productName(productName)
                .productId(productId)
                .price(price)
                .build();

        assertEquals(id, order.getId());
        assertEquals(productName, order.getProductName());
        assertEquals(productId, order.getProductId());
        assertEquals(price, order.getPrice());
    }
}